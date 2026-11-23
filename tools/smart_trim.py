import math
import re
from collections import Counter
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


def _normalise_max_chars(value: Any, default: int = 30000) -> int:
    try:
        max_chars = int(value)
    except (TypeError, ValueError):
        return default
    return max_chars if max_chars > 0 else default


class SmartTrimTool(Tool):
    def _yield_outputs(
        self,
        text: str,
        original_length: int,
        processed_length: int,
        was_trimmed: bool,
        algorithm: str,
    ) -> Generator[ToolInvokeMessage, None, None]:
        ratio = (
            1.0 if original_length == 0 else original_length / max(processed_length, 1)
        )
        compression_ratio = round(ratio, 4)
        yield self.create_text_message(text)
        yield self.create_variable_message("original_char_count", original_length)
        yield self.create_variable_message("processed_char_count", processed_length)
        yield self.create_variable_message("compression_ratio", compression_ratio)
        yield self.create_variable_message("was_trimmed", was_trimmed)
        yield self.create_variable_message("algorithm", algorithm)
        yield self.create_json_message(
            {
                "text": text,
                "original_char_count": original_length,
                "processed_char_count": processed_length,
                "compression_ratio": compression_ratio,
                "was_trimmed": was_trimmed,
                "algorithm": algorithm,
            }
        )

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        try:
            yield from self._do_invoke(tool_parameters)
        # The fallback must cover any processing failure to enforce max_chars.
        except Exception:  # noqa: BLE001
            import sys
            import traceback

            traceback.print_exc(file=sys.stderr)
            raw_text = tool_parameters.get("text")
            fallback_text = raw_text if isinstance(raw_text, str) else ""
            fallback_len = len(fallback_text)
            max_chars = _normalise_max_chars(tool_parameters.get("max_chars"))
            safe_text = _boundary_aware_truncate(fallback_text, max_chars)
            yield from self._yield_outputs(
                text=safe_text,
                original_length=fallback_len,
                processed_length=len(safe_text),
                was_trimmed=fallback_len > len(safe_text),
                algorithm="error_truncation",
            )

    def _do_invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        text = tool_parameters.get("text") or ""
        max_chars = _normalise_max_chars(tool_parameters.get("max_chars"))

        method = tool_parameters.get("method", "mmr")
        if method not in ("greedy", "mmr"):
            method = "mmr"
        try:
            diversity = float(tool_parameters.get("mmr_lambda", 0.7))
        except (TypeError, ValueError):
            diversity = 0.7
        if diversity < 0.0:
            diversity = 0.0
        elif diversity > 1.0:
            diversity = 1.0

        original_length = len(text)

        if original_length <= max_chars:
            yield from self._yield_outputs(
                text=text,
                original_length=original_length,
                processed_length=original_length,
                was_trimmed=False,
                algorithm="passthrough",
            )
            return

        processed_text, algorithm = _extract_key_sentences(
            text,
            max_chars,
            method=method,
            diversity=diversity,
        )
        processed_length = len(processed_text)

        yield from self._yield_outputs(
            text=processed_text,
            original_length=original_length,
            processed_length=processed_length,
            was_trimmed=True,
            algorithm=algorithm,
        )


# Maximum number of sentences to run MMR on directly. For larger documents,
# candidates are pre-filtered to this cap by score before MMR selection.
# With incremental overlap tracking, MMR is O(k×n) per selection round.
# Full MMR is safe up to this threshold; beyond it, candidates are
# pre-filtered to _MMR_CANDIDATE_CAP by score before running MMR.
_MMR_FULL_LIMIT = 5000

# Pre-filter target size: when the document exceeds _MMR_FULL_LIMIT
# sentences, only the top-scoring _MMR_CANDIDATE_CAP candidates are
# passed to MMR.  This bounds the MMR inner loop to a fixed budget
# regardless of input size.
#
# The pre-filter only bounds the MMR loop; it must not bound the output.
# The sentences it leaves out are added back by _fill_remaining_budget,
# so a large document still yields as much text as the caller asked for.
_MMR_CANDIDATE_CAP = 5000

# Common English abbreviations that should NOT be treated as sentence boundaries.
_ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "ave",
        "blvd",
        "inc",
        "corp",
        "ltd",
        "co",
        "etc",
        "vs",
        "viz",
        "ie",
        "eg",
        "apt",
        "dept",
        "div",
        "est",
        "gov",
        "mil",
        "op",
        "ord",
        "pvt",
        "rep",
        "sen",
        "sgt",
        "capt",
        "cmdr",
        "lt",
        "col",
        "gen",
        "rev",
        "hon",
        "pres",
        "vp",
        "ceo",
        "cfo",
        "coo",
        "ct",
        "fig",
        "eq",
        "approx",
        "esp",
    }
)


def _is_cjk_char(c: str) -> bool:
    """Return True if *c* is a CJK ideograph or Japanese kana character."""
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x2EBEF
        or 0x3040 <= cp <= 0x309F
        or 0x30A0 <= cp <= 0x30FF
        or 0xFF65 <= cp <= 0xFF9F
    )


# Pre-compiled abbreviation protection regexes — compiled once at import time
# rather than on every _split_sentences call.
_ABBREV_PATTERN = re.compile(
    r"\b(" + "|".join(_ABBREVIATIONS) + r")\.\s+(?=[A-Z0-9一-鿿぀-ゟ゠-ヿ])",
    re.IGNORECASE,
)

_INITIALISM_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]\.){2,}")
_MIDDLE_INITIAL_PATTERN = re.compile(r"(\b[A-Z][a-z]+\s)([A-Z])\.(?=\s+[A-Z][a-z]+)")

_CLOSING_PUNCTUATION = "\"'”’」』）)]}】》〉〕］｝"
_CJK_SENTENCE_END_PATTERN = re.compile(
    rf"[。！？…]+[{re.escape(_CLOSING_PUNCTUATION)}]*\s*"
)
_ENGLISH_SENTENCE_END_PATTERN = re.compile(
    rf"[.!?]+[{re.escape(_CLOSING_PUNCTUATION)}]*(?:\s+)(?=[A-Z0-9一-鿿぀-ゟ゠-ヿ])"
)
_NEWLINE_BOUNDARY_PATTERN = re.compile(r"\r?\n+")


def _extract_key_sentences(
    text: str,
    max_chars: int,
    method: str = "greedy",
    diversity: float = 0.7,
) -> tuple[str, str]:
    """Extract the most important sentences from text to fit within max_chars.

    Supports Chinese, Japanese, and English text.

    Algorithm overview (see README for full details):
    1. Segment text into sentences (CJK + Japanese + English punctuation aware)
    2. Score each sentence by position, keyword density, and length
    3. Select top-scoring sentences (greedy or MMR diversity-aware)
    4. Reorder selected sentences by original position for coherence
    5. If no sentence fits the budget, fall back to boundary-aware truncation

    Returns:
        (processed_text, algorithm_name) where algorithm_name is one of
        "greedy", "mmr", "mmr_prefilter", or "boundary_truncation".
    """
    sentences = _split_sentences(text)
    if not sentences:
        return _boundary_aware_truncate(text, max_chars), "boundary_truncation"

    total_sentences = len(sentences)
    scores, sentence_tokens = _score_sentences(sentences, total_sentences)

    if method == "greedy":
        selected_indices = _greedy_select(sentences, scores, max_chars)
        algorithm = "greedy"
    else:
        if len(sentences) > _MMR_FULL_LIMIT:
            # Pre-filter to a fixed-size candidate pool before MMR.
            # The pre-filter uses the same scores, so only the
            # diversity penalty is computed on the reduced set.
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            kept = {i for i, _ in ranked[:_MMR_CANDIDATE_CAP]}
            filtered_sentences = [s for i, s in enumerate(sentences) if i in kept]
            filtered_scores = [s for i, s in enumerate(scores) if i in kept]
            filtered_tokens = [t for i, t in enumerate(sentence_tokens) if i in kept]
            selected_indices = _mmr_select(
                filtered_sentences,
                filtered_scores,
                filtered_tokens,
                max_chars,
                diversity,
            )
            if selected_indices:
                # Map back to original indices for position-based reordering
                kept_list = sorted(kept)
                selected_indices = [kept_list[i] for i in selected_indices]
            # The pre-filter limited which sentences MMR could choose from,
            # not how much text the tool may return. Complete the result with
            # the best sentences the pre-filter left out.
            selected_indices = _fill_remaining_budget(
                sentences,
                scores,
                selected_indices,
                max_chars,
            )
            algorithm = "mmr_prefilter"
        else:
            selected_indices = _mmr_select(
                sentences,
                scores,
                sentence_tokens,
                max_chars,
                diversity,
            )
            algorithm = "mmr"

    if not selected_indices:
        return _boundary_aware_truncate(text, max_chars), "boundary_truncation"

    selected_indices.sort()
    return "".join(sentences[i] for i in selected_indices), algorithm


def _greedy_select(
    sentences: list[str],
    scores: list[float],
    max_chars: int,
) -> list[int]:
    """Select sentences by simple greedy top-score order (O(n log n)).

    Fast path for when diversity is not required. Sentences are sorted by
    score descending and added until the character budget is exhausted.
    """
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected_indices: list[int] = []
    total_chars = 0
    for idx, _score in ranked:
        sent_len = len(sentences[idx])
        if total_chars + sent_len > max_chars:
            continue
        selected_indices.append(idx)
        total_chars += sent_len
    return selected_indices


def _mmr_select(
    sentences: list[str],
    scores: list[float],
    sentence_tokens: list[list[str]],
    max_chars: int,
    lambda_mmr: float = 0.7,
) -> list[int]:
    """Select sentences using Maximal Marginal Relevance (MMR).

    Balances relevance (high score) with diversity (low overlap with
    already-selected sentences). Tracks per-candidate max_overlap incrementally
    so each selection round is O(n) instead of O(n*k), yielding O(n*k) overall.
    """
    n = len(sentences)
    sent_token_sets: list[set[str]] = [set(t) for t in sentence_tokens]
    inv_lambda = 1.0 - lambda_mmr

    selected_indices: list[int] = []
    total_chars = 0
    remaining: dict[int, float] = {}

    max_overlap: list[float] = [0.0] * n

    for i, sent in enumerate(sentences):
        if len(sent) <= max_chars:
            remaining[i] = lambda_mmr * scores[i] + inv_lambda * 1.0

    while remaining:
        # Pick the candidate with the highest current MMR score
        best_idx = max(remaining, key=remaining.get)
        sent_len = len(sentences[best_idx])

        if total_chars + sent_len > max_chars:
            del remaining[best_idx]
            continue

        selected_indices.append(best_idx)
        total_chars += sent_len
        newly_selected = sent_token_sets[best_idx]
        del remaining[best_idx]

        # Update diversity penalty incrementally — only compare with the
        # newly-selected sentence instead of all previously-selected ones
        for idx in list(remaining):
            overlap = _token_overlap_ratio(sentence_tokens[idx], newly_selected)
            max_overlap[idx] = max(max_overlap[idx], overlap)
            diversity = 1.0 - max_overlap[idx]
            remaining[idx] = lambda_mmr * scores[idx] + inv_lambda * diversity

    return selected_indices


def _fill_remaining_budget(
    sentences: list[str],
    scores: list[float],
    selected_indices: list[int],
    max_chars: int,
) -> list[int]:
    """Complete the selection with the best sentences that are still unused.

    The MMR pre-filter makes only the top _MMR_CANDIDATE_CAP sentences
    eligible for selection. That bounds the MMR loop, but without this step
    it also caps the output: on a large document the tool would return the
    candidate pool and drop the rest of the document even when the budget
    had room for it.

    The remaining budget is filled with the highest-scoring unselected
    sentences, in the same way the greedy selection does.
    """
    used = sum(len(sentences[i]) for i in selected_indices)
    if used >= max_chars:
        return selected_indices

    chosen = set(selected_indices)
    ranked = sorted(
        (i for i in range(len(sentences)) if i not in chosen),
        key=lambda i: scores[i],
        reverse=True,
    )
    for idx in ranked:
        sent_len = len(sentences[idx])
        if used + sent_len > max_chars:
            continue
        selected_indices.append(idx)
        used += sent_len
        if used >= max_chars:
            break
    return selected_indices


def _token_overlap_ratio(tokens_a: list[str], tokens_b: set[str]) -> float:
    """Compute the ratio of tokens in a that also appear in b.

    Used as a similarity measure for MMR diversity penalty.
    Returns 0.0 if tokens_a is empty.
    """
    if not tokens_a:
        return 0.0
    overlap = sum(1 for t in tokens_a if t in tokens_b)
    return overlap / len(tokens_a)


def _boundary_aware_truncate(text: str, max_chars: int) -> str:
    """Truncate text at the best available boundary within max_chars.

    Tries to find the last sentence-ending punctuation (CJK or English)
    within the budget. Falls back to the last whitespace boundary.
    Last resort: hard truncation with ellipsis indicator.
    """
    if len(text) <= max_chars:
        return text

    chunk = text[:max_chars]

    # Try to truncate at the last sentence-ending punctuation
    last_punct = -1
    for punct in ["。", "！", "？", ".", "!", "?"]:
        pos = chunk.rfind(punct)
        last_punct = max(last_punct, pos)

    if last_punct > max_chars * 0.5:
        # Keep at least 50% of the budget — don't truncate too aggressively
        return text[: last_punct + 1]

    # Try whitespace boundary
    last_space = chunk.rfind(" ")
    if last_space > max_chars * 0.5:
        return text[:last_space]

    # Hard truncation with ellipsis (guard against implausibly small max_chars)
    if max_chars < 4:
        return text[:max_chars]
    is_cjk = any(_is_cjk_char(c) for c in text[:max_chars])
    ellipsis = "……" if is_cjk else "..."
    return text[: max_chars - len(ellipsis)] + ellipsis


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences supporting CJK, Japanese, and English punctuation.

    Handles edge cases: decimal numbers (3.14), abbreviations (Mr.),
    ellipsis (... / ……), and CJK punctuation variants.
    """
    # Protect periods in a same-length copy so boundary offsets still map
    # directly to the original text.
    protected = _INITIALISM_PATTERN.sub(
        lambda match: match.group(0).replace(".", "\x00"), text
    )
    protected = _MIDDLE_INITIAL_PATTERN.sub(
        lambda match: match.group(1) + match.group(2) + "\x00",
        protected,
    )
    protected = _ABBREV_PATTERN.sub(
        lambda match: match.group(0).replace(".", "\x00"),
        protected,
    )

    boundary_ends = {
        match.end()
        for pattern in (
            _CJK_SENTENCE_END_PATTERN,
            _ENGLISH_SENTENCE_END_PATTERN,
            _NEWLINE_BOUNDARY_PATTERN,
        )
        for match in pattern.finditer(protected)
    }

    sentences: list[str] = []
    start = 0
    for end in sorted(boundary_ends | {len(text)}):
        sentence = text[start:end]
        if sentence.strip():
            sentences.append(sentence)
        start = end
    return sentences


def _score_sentences(
    sentences: list[str], total_count: int
) -> tuple[list[float], list[list[str]]]:
    """Score each sentence and return scores together with cached token lists.

    Tokenization is done once here — results are reused by the selection
    phase (greedy or MMR), avoiding redundant re-tokenization.
    """
    sentence_tokens = [_tokenize(s) for s in sentences]
    df_counter = _build_df_counter(sentence_tokens)
    scores = []
    for i, (sent, tokens) in enumerate(zip(sentences, sentence_tokens)):
        position_score = _position_score(i, total_count)
        keyword_score = _keyword_density_score(tokens, df_counter, total_count)
        length_score = _length_score(sent)
        composite = 0.3 * position_score + 0.5 * keyword_score + 0.2 * length_score
        scores.append(composite)
    return scores, sentence_tokens


def _build_df_counter(sentence_tokens: list[list[str]]) -> Counter:
    """Build document frequency: how many sentences contain each token.

    Each sentence contributes at most 1 per unique token (set-based),
    so the result is the number of sentences each token appears in.
    """
    df_counter: Counter = Counter()
    for tokens in sentence_tokens:
        df_counter.update(set(tokens))
    return df_counter


def _tokenize(text: str) -> list[str]:
    """Tokenize mixed CJK/Japanese/English text.

    CJK ideographs and Japanese kana are treated as individual tokens.
    English words are extracted via word-boundary regex.
    Punctuation and whitespace are excluded.
    """
    tokens: list[str] = []
    for char in text:
        if _is_cjk_char(char):
            tokens.append(char)
    words = re.findall(r"[a-zA-Z0-9]+", text)
    tokens.extend(w.lower() for w in words if len(w) > 1)
    return tokens


def _position_score(index: int, total: int) -> float:
    """Score sentence by its position in the document.

    First 20% (intro) and last 10% (conclusion) get higher weights.
    Middle sentences decay linearly.
    """
    if total <= 1:
        return 1.0
    ratio = index / (total - 1)
    if ratio <= 0.2:
        return 1.0 - 0.3 * (ratio / 0.2)
    if ratio >= 0.9:
        return 0.2 + 0.8 * ((ratio - 0.9) / 0.1)
    return 0.7 - 0.5 * ((ratio - 0.2) / 0.7)


def _keyword_density_score(
    tokens: list[str],
    df_counter: Counter,
    total_sentences: int,
) -> float:
    """Score sentence using normalized TF-IDF.

    TF (term frequency): how prominent is this term within the sentence.
    IDF (inverse document frequency): how rare is this term across all sentences.
    High TF-IDF means the term is both salient to this sentence and
    discriminative — naturally downweighting function words like 的/the/は
    that appear in nearly every sentence.

    The score is normalized by the number of unique tokens to prevent
    bias toward sentences with larger vocabulary size.
    """
    if not tokens:
        return 0.0
    sent_counter = Counter(tokens)
    sent_len = len(tokens)
    unique_count = len(sent_counter)
    score = 0.0
    for token, count in sent_counter.items():
        tf = count / sent_len
        df = df_counter.get(token, 0)
        idf = math.log((total_sentences + 1) / (df + 1)) + 1.0
        score += tf * idf
    # Normalize by unique token count to prevent vocabulary-size bias
    return score / unique_count if unique_count > 0 else 0.0


def _length_score(sentence: str) -> float:
    """Score sentence based on its character length.

    Penalizes very short (<10 chars, likely filler) or very long
    (>200 chars, likely verbose) sentences. Ideal range is 20-150 chars.
    """
    length = len(sentence)
    if length < 10:
        return 0.15
    if length <= 20:
        return 0.15 + 0.75 * (length - 10) / 10
    if length <= 150:
        return 0.9 + 0.1 * (length - 20) / 130
    if length <= 200:
        return 1.0 - 0.4 * (length - 150) / 50
    return max(0.3, 0.6 - 0.3 * (length - 200) / 300)
