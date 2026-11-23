"""Fuzz target for the smart_trim output contract.

The plugin's central promise is that the tool never returns more than
``max_chars`` characters -- on every path, including the internal-error
fallback. The unit tests pin that promise down with fixed samples; this
harness attacks the same promise with random input.

Atheris bundles libFuzzer and ships Linux-only wheels, so the harness runs in
CI on ubuntu-latest:

    uv run --group fuzz python -m tests.fuzz_smart_trim -max_total_time=60
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import atheris

from tools.smart_trim import (
    SmartTrimTool,
    _extract_key_sentences,
    _normalise_max_chars,
)

# Every algorithm value the tool is allowed to report.
ALGORITHMS = frozenset(
    {
        "passthrough",
        "greedy",
        "mmr",
        "mmr_prefilter",
        "boundary_truncation",
        "error_truncation",
    }
)

# Every algorithm the trimming core can return on its own.
CORE_ALGORITHMS = frozenset(
    {
        "greedy",
        "mmr",
        "mmr_prefilter",
        "boundary_truncation",
    }
)

# Upper bound on the text built from one fuzzer input, so a single iteration
# stays fast enough for the fuzzer to explore many inputs per second.
MAX_INPUT_CHARS = 1000

# Sentence terminators for every script the splitter understands. Interleaved
# with the fuzzer's own bytes, they steer the splitter down each of its paths.
FILLERS = (
    "",
    "。",
    ".",
    "!\n",
    "? ",
    "Mr. Smith went to Washington. ",
    "「最初の文です。」",
    "他说：“你好。”然后离开了。",
    "\n",
)


class _FakeSmartTrimTool(SmartTrimTool):
    """Stand-in for the SDK tool that records emitted messages as tuples."""

    def create_text_message(self, text):
        return ("text", text)

    def create_variable_message(self, name, value):
        return ("var", name, value)

    def create_json_message(self, value):
        return ("json", value)


def _build_text(data: bytes) -> str:
    """Turn raw fuzzer bytes into text that hits every sentence-splitting path."""
    decoded = data[:MAX_INPUT_CHARS].decode("utf-8", errors="ignore")
    parts = []
    for index, char in enumerate(decoded):
        parts.append(char)
        parts.append(FILLERS[index % len(FILLERS)])
    return "".join(parts)


def _pick_max_chars(data: bytes, length: int) -> int:
    """Pick a budget that is sometimes below and sometimes above the length."""
    choices = (
        0,
        1,
        2,
        3,
        4,
        5,
        8,
        13,
        21,
        34,
        55,
        89,
        144,
        length // 8,
        length // 4,
        length // 2,
        length,
        length + 1,
    )
    if not data:
        return choices[0]
    return choices[data[0] % len(choices)]


def _pick_method(data: bytes) -> str:
    return "greedy" if data[1:2] == b"g" else "mmr"


def _pick_diversity(data: bytes) -> float:
    if len(data) <= 2:
        return 0.7
    return data[2] / 255.0


def _fuzz_core(data: bytes) -> None:
    """The trimming core must never return more than the budget."""
    text = _build_text(data)
    max_chars = _pick_max_chars(data, len(text))

    result, algorithm = _extract_key_sentences(
        text,
        max_chars,
        method=_pick_method(data),
        diversity=_pick_diversity(data),
    )

    assert len(result) <= max_chars, (
        f"{algorithm} returned {len(result)} chars for a budget of {max_chars}"
    )
    assert algorithm in CORE_ALGORITHMS, f"unexpected algorithm {algorithm!r}"


def _fuzz_tool(data: bytes) -> None:
    """The tool output contract must hold for every input."""
    text = _build_text(data)
    raw_max_chars = _pick_max_chars(data, len(text))
    max_chars = _normalise_max_chars(raw_max_chars)

    tool = _FakeSmartTrimTool.__new__(_FakeSmartTrimTool)
    messages = list(
        tool._invoke(
            {
                "text": text,
                "max_chars": raw_max_chars,
                "method": _pick_method(data),
                "mmr_lambda": _pick_diversity(data),
            }
        )
    )

    assert len(messages) == 7, f"expected 7 messages, got {len(messages)}"
    assert messages[0][0] == "text"
    output = messages[0][1]
    assert len(output) <= max_chars, (
        f"tool returned {len(output)} chars for a budget of {max_chars}"
    )

    variables = {message[1]: message[2] for message in messages if message[0] == "var"}
    json_messages = [message for message in messages if message[0] == "json"]
    assert len(json_messages) == 1, "exactly one JSON message must be emitted"
    payload = json_messages[0][1]

    assert "error" not in variables, "the traceback must not leak into variables"
    assert "error" not in payload, "the traceback must not leak into the JSON"
    assert variables["algorithm"] in ALGORITHMS
    assert variables["original_char_count"] == len(text)
    assert variables["processed_char_count"] == len(output)
    assert isinstance(variables["was_trimmed"], bool)
    assert isinstance(variables["compression_ratio"], float)
    assert payload["text"] == output
    assert payload["algorithm"] == variables["algorithm"]

    if len(text) <= max_chars:
        # Short enough to pass through: the input must come back untouched.
        assert variables["algorithm"] == "passthrough"
        assert output == text, "passthrough must not rewrite the input"
        assert variables["was_trimmed"] is False


def TestOneInput(data: bytes) -> None:
    """Atheris entry point."""
    _fuzz_core(data)
    _fuzz_tool(data)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
