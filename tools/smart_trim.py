import math
import re
from collections import Counter
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


class SmartTrimTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        try:
            yield from self._do_invoke(tool_parameters)
        except Exception:
            import sys
            import traceback
            exc = traceback.format_exc()
            print(exc, file=sys.stderr, flush=True)
            yield self.create_text_message(
                tool_parameters.get("text") or ""
            )
            yield self.create_variable_message("original_char_count", 0)
            yield self.create_variable_message("processed_char_count", 0)
            yield self.create_variable_message("was_trimmed", False)

    def _do_invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        text = tool_parameters.get("text") or ""
        try:
            max_chars = int(tool_parameters.get("max_chars", 30000))
        except (TypeError, ValueError):
            max_chars = 30000
        if max_chars <= 0:
            max_chars = 30000

        method = tool_parameters.get("method", "mmr")
        if method not in ("greedy", "mmr"):
            method = "greedy"
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
            yield self.create_text_message(text)
            yield self.create_variable_message("original_char_count", original_length)
            yield self.create_variable_message("processed_char_count", original_length)
            yield self.create_variable_message("was_trimmed", False)
            return

        processed_text = _extract_key_sentences(
            text, max_chars,
            method=method,
            diversity=diversity,
        )
        processed_length = len(processed_text)

        yield self.create_text_message(processed_text)
        yield self.create_variable_message("original_char_count", original_length)
        yield self.create_variable_message("processed_char_count", processed_length)
        yield self.create_variable_message("was_trimmed", True)


# Common English abbreviations that should NOT be treated as sentence boundaries.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave", "blvd",
    "inc", "corp", "ltd", "co", "etc", "vs", "viz", "ie", "eg",
    "apt", "dept", "div", "est", "gov", "mil", "op", "ord", "pvt",
    "rep", "sen", "sgt", "capt", "cmdr", "lt", "col", "gen",
    "rev", "hon", "pres", "vp", "ceo", "cfo", "coo", "ct",
})


def _extract_key_sentences(
    text: str,
    max_chars: int,
    method: str = "greedy",
    diversity: float = 0.7,
) -> str:
    """Extract the most important sentences from text to fit within max_chars.

    Supports Chinese, Japanese, and English text.

    Algorithm overview (see README for full details):
    1. Segment text into sentences (CJK + Japanese + English punctuation aware)
    2. Score each sentence by position, keyword density, and length
    3. Select top-scoring sentences (greedy or MMR diversity-aware)
    4. Reorder selected sentences by original position for coherence
    5. If no sentence fits the budget, fall back to boundary-aware truncation
    """
    sentences = _split_sentences(text)
    if not sentences:
        return _boundary_aware_truncate(text, max_chars)

    total_sentences = len(sentences)
    scores, sentence_tokens = _score_sentences(sentences, total_sentences)

    if method == "greedy":
        selected_indices = _greedy_select(sentences, scores, max_chars)
    else:
        # MMR-style selection balancing relevance with diversity
        selected_indices = _mmr_select(
            sentences, scores, sentence_tokens, max_chars, diversity,
        )

    if not selected_indices:
        return _boundary_aware_truncate(text, max_chars)

    selected_indices.sort()
    return "".join(sentences[i] for i in selected_indices)


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
    already-selected sentences). This reduces redundant content in the
    output summary.

    Args:
        sentences: List of sentence strings.
        scores: Composite scores for each sentence.
        max_chars: Character budget.
        lambda_mmr: Relevance vs. diversity trade-off (0 = pure diversity,
            1 = pure relevance). Default 0.7 favors relevance moderately.

    Returns:
        List of selected sentence indices (unordered).
    """
    selected_indices: list[int] = []
    selected_tokens: list[set[str]] = []
    total_chars = 0
    remaining = set(range(len(sentences)))

    while remaining:
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            sent_len = len(sentences[idx])
            if total_chars + sent_len > max_chars:
                continue

            relevance = scores[idx]

            # Diversity: penalize overlap with already-selected sentences
            if selected_tokens:
                max_overlap = max(
                    _token_overlap_ratio(sentence_tokens[idx], st)
                    for st in selected_tokens
                )
                diversity = 1.0 - max_overlap
            else:
                diversity = 1.0  # No penalty for the first selection

            mmr = lambda_mmr * relevance + (1.0 - lambda_mmr) * diversity

            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx == -1:
            break  # No more sentences fit the budget

        selected_indices.append(best_idx)
        selected_tokens.append(set(sentence_tokens[best_idx]))
        total_chars += len(sentences[best_idx])
        remaining.discard(best_idx)

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
        if pos > last_punct:
            last_punct = pos

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
    return text[:max_chars - 3] + "..."


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences supporting CJK, Japanese, and English punctuation.

    Handles edge cases: decimal numbers (3.14), abbreviations (Mr.),
    ellipsis (... / ……), and CJK punctuation variants.
    """
    # Protect abbreviations from being split: replace "Mr." period with a placeholder
    # Pattern: known abbreviation (case-insensitive) followed by a period and space+capital
    abbrev_pattern = re.compile(
        r"\b(" + "|".join(_ABBREVIATIONS) + r")\.\s+(?=[A-Z])",
        re.IGNORECASE,
    )
    text = abbrev_pattern.sub(lambda m: m.group(0).replace(".", "\x00"), text)

    # CJK fullwidth sentence-ending punctuation (Chinese / Japanese)
    # Note: ；(fullwidth semicolon) is excluded — in Chinese it separates
    # clauses within a sentence, not sentence boundaries.
    text = re.sub(r"([。！？])(?=[^\n])", r"\1\n", text)

    # CJK closing brackets that often end sentences (Japanese)
    text = re.sub(r"([」』])(?=[^\n])", r"\1\n", text)

    # English halfwidth sentence-ending punctuation followed by capital or CJK
    text = re.sub(r"([.!?])(\s+)(?=[A-Z一-鿿぀-ゟ゠-ヿ])", r"\1\2\n", text)

    # Ellipsis followed by capital or CJK
    # English: 3+ dots; CJK: 2+ … characters (U+2026)
    text = re.sub(r"(\.{3,}|…{2,})(?=[A-Z一-鿿぀-ゟ゠-ヿ])", r"\1\n", text)

    # Restore abbreviation periods
    text = text.replace("\x00", ".")

    sentences = []
    for sent in re.split(r"\n+", text):
        stripped = sent.strip()
        if stripped:
            sentences.append(stripped)
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
        if (
            "\u4e00" <= char <= "\u9fff"  # CJK Unified Ideographs
            or "\u3400" <= char <= "\u4dbf"  # CJK Extension A
            or "\u3040" <= char <= "\u309f"  # Hiragana
            or "\u30a0" <= char <= "\u30ff"  # Katakana
        ):
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
    if length < 20:
        return 0.5
    if length <= 150:
        return 0.9 + 0.1 * min((length - 20) / 130, 1.0)
    if length <= 200:
        return 0.6
    return 0.3
