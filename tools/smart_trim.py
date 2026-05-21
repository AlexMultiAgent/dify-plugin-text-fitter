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
        text = tool_parameters.get("text", "")
        max_chars = int(tool_parameters.get("max_chars", 30000))

        original_length = len(text)

        if original_length <= max_chars:
            yield self.create_text_message(text)
            yield self.create_variable_message("original_char_count", original_length)
            yield self.create_variable_message("processed_char_count", original_length)
            yield self.create_variable_message("was_trimmed", False)
            return

        processed_text = _extract_key_sentences(text, max_chars)
        processed_length = len(processed_text)

        yield self.create_text_message(processed_text)
        yield self.create_variable_message("original_char_count", original_length)
        yield self.create_variable_message("processed_char_count", processed_length)
        yield self.create_variable_message("was_trimmed", True)


def _extract_key_sentences(text: str, max_chars: int) -> str:
    """Extract the most important sentences from text to fit within max_chars.

    Algorithm overview (see README for full details):
    1. Segment text into sentences (Chinese + English punctuation aware)
    2. Score each sentence by position, keyword density, and length
    3. Greedily select top-scoring sentences within the character budget
    4. Reorder selected sentences by original position for coherence
    """
    sentences = _split_sentences(text)
    if not sentences:
        return text[:max_chars]

    total_sentences = len(sentences)
    scores = _score_sentences(sentences, total_sentences)

    ranked = sorted(
        enumerate(scores), key=lambda x: x[1], reverse=True
    )

    selected_indices = []
    total_chars = 0
    for idx, _score in ranked:
        sent_len = len(sentences[idx])
        if total_chars + sent_len > max_chars:
            continue
        selected_indices.append(idx)
        total_chars += sent_len

    selected_indices.sort()

    return "".join(sentences[i] for i in selected_indices)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences supporting Chinese and English punctuation.

    Handles edge cases: decimal numbers (3.14), abbreviations (Mr.),
    ellipsis (...), and common Chinese dot separators.
    """
    # Insert newlines after Chinese sentence-ending punctuation
    text = re.sub(r"([。！？；])(?=[^\n])", r"\1\n", text)
    # Insert newlines after English sentence-ending punctuation followed by capital/Chinese
    text = re.sub(r"([.!?])(\s+)(?=[A-Z一-鿿])", r"\1\2\n", text)
    # Insert newlines after ellipsis followed by capital/Chinese
    text = re.sub(r"(\.{3,})(?=[A-Z一-鿿])", r"\1\n", text)

    sentences = []
    for sent in re.split(r"\n+", text):
        stripped = sent.strip()
        if stripped:
            sentences.append(stripped)
    return sentences


def _score_sentences(sentences: list[str], total_count: int) -> list[float]:
    """Score each sentence by a composite of position, keyword, and length scores."""
    word_counter = _build_word_counter(sentences)
    scores = []
    for i, sent in enumerate(sentences):
        position_score = _position_score(i, total_count)
        keyword_score = _keyword_density_score(sent, word_counter)
        length_score = _length_score(sent)
        composite = 0.3 * position_score + 0.5 * keyword_score + 0.2 * length_score
        scores.append(composite)
    return scores


def _build_word_counter(sentences: list[str]) -> Counter:
    """Build a word frequency counter from all sentences.

    Tokenizes Chinese text by individual characters and English text by words.
    """
    counter: Counter = Counter()
    for sent in sentences:
        tokens = _tokenize(sent)
        counter.update(tokens)
    return counter


def _tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese-English text.

    Chinese characters are treated as individual tokens.
    English words are extracted via word-boundary regex.
    Punctuation and whitespace are excluded.
    """
    tokens: list[str] = []
    for char in text:
        if "一" <= char <= "鿿" or "㐀" <= char <= "䶿":
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
        return 0.7 + 0.3 * (1.0 - ratio / 0.2)
    if ratio >= 0.9:
        return 0.6 + 0.4 * ((ratio - 0.9) / 0.1)
    return 0.5 - 0.3 * ((ratio - 0.2) / 0.7)


def _keyword_density_score(sentence: str, word_counter: Counter) -> float:
    """Score sentence by the average frequency of its constituent words.

    Words that appear often across the document are likely keywords;
    sentences containing them are more representative.
    """
    tokens = _tokenize(sentence)
    if not tokens:
        return 0.0
    total_freq = sum(word_counter.get(t, 0) for t in tokens)
    return total_freq / (len(tokens) + 1)


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
