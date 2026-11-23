# Text Fitter

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/AlexMultiAgent/dify-plugin-text-fitter/badge)](https://api.scorecard.dev/projects/github.com/AlexMultiAgent/dify-plugin-text-fitter)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/17040/badge)](https://www.bestpractices.dev/projects/17040)

A Dify tool plugin that ensures text fits within LLM context window limits
via intelligent extractive summarization. Supports Chinese (Simplified &
Traditional), Japanese, and English text.

> **Source**: [github.com/AlexMultiAgent/dify-plugin-text-fitter](https://github.com/AlexMultiAgent/dify-plugin-text-fitter)

## Requirements

- **No API keys or credentials** — the plugin runs in-process and calls no external service.
- **No network connection** — all processing is local and in-memory.
- Dify platform (Community Edition or Cloud) 1.14.0 or later with plugin support enabled.

## Why

Locally deployed or resource-constrained LLM instances often have a smaller
effective context window than the model's official specification — due to
hardware limits (GPU VRAM), concurrency requirements, or serving parameters
like `--max-model-len`. When input text exceeds the window, the LLM fails
with a context-length error.

This plugin acts as a pre-processing guard: it measures the input, and if it
exceeds a user-configured threshold, trims it by extracting only the
highest-scoring sentences — before the text ever reaches the LLM. No API
keys, no network calls, and no external NLP dependencies.

## Installation

### From Dify Marketplace

1. In your Dify workspace, go to **Plugins** → **Marketplace**.
2. Search for **Text Fitter** and click **Install**.
3. The plugin will appear in your workflow tools as **Smart Trim**.

### Manual Installation

1. Download the `.difypkg` file from the GitHub releases page.
2. In Dify, go to **Plugins** → **Install Plugin** → **Upload Package**.
3. Upload the `.difypkg` file.

## Usage

1. In a workflow, add the **Smart Trim** node from the tool palette.
2. Wire `text` to your upstream content source (document parser, HTTP input, etc.).
3. Set `max_chars` to a value below your LLM's effective context limit.
4. Connect the node's text output to your downstream LLM node.
5. Optionally use `was_trimmed` to branch logic (e.g., log a warning when trimming occurred).

### Choosing max_chars

`max_chars` is a character count threshold — the plugin checks `len(input)`
against it. It does not measure tokens.

As a rough guide, using the Qwen3 BBPE tokenizer (~151K vocab; Qwen3 Technical Report, 2025):

| Language | Tokens per char             | Chars fitting in 20K tokens |
| -------- | --------------------------- | --------------------------- |
| English  | ~0.25 (1 token ≈ 4 chars)   | ~80,000                     |
| Chinese  | ~0.6 (1 token ≈ 1.7 chars)  | ~33,000                     |
| Japanese | ~0.8 (1 token ≈ 1.3 chars)  | ~25,000                     |

> Token-to-character ratios vary across tokenizers (source: TokLens, ACL 2026 SRW).
> Always verify with your specific model when precise budgeting is critical.

Reserve ~80% of the context window for input text, leaving ~20% headroom for
the next LLM node's prompt templates and output generation.

## Parameters

| Parameter    | Type   | Required | Default | Description                                                                       |
| ------------ | ------ | -------- | ------- | --------------------------------------------------------------------------------- |
| `text`       | string | Yes      | —       | Input text to process                                                             |
| `max_chars`  | number | Yes      | 30000   | Character threshold; exceeding triggers trimming                                  |
| `method`     | select | No       | `mmr`   | Sentence selection: `"mmr"` (diverse) or `"greedy"` (fast)                        |
| `mmr_lambda` | select | No       | `0.7`   | MMR relevance weight. 0.0 (diversity) to 1.0 (relevance). Ignored with `"greedy"` |

## Outputs

| Output                 | Type    | Description                                                    |
| ---------------------- | ------- | -------------------------------------------------------------- |
| `text`                 | string  | The processed text (original or trimmed)                       |
| `original_char_count`  | number  | Character count of the original input text                     |
| `processed_char_count` | number  | Character count of the output text                             |
| `was_trimmed`          | boolean | Whether the text was trimmed                                   |
| `compression_ratio`    | number  | Compression ratio (original / processed). 1.0 when not trimmed |
| `algorithm`            | string  | Algorithm actually used. See [Algorithm](#algorithm)           |

## Language Support

The plugin ships translations for four locales:

| Locale    | Language            |
| --------- | ------------------- |
| `en_US`   | English             |
| `zh_Hans` | Simplified Chinese  |
| `zh_Hant` | Traditional Chinese |
| `ja_JP`   | Japanese            |

All parameter labels, descriptions, and option values are translated across
those locales.

Dify renders three of them today. The plugin manifest format carries
`en_US`, `zh_Hans`, `ja_JP` and `pt_BR` only, so the `zh_Hant` strings fall
back to English in the Dify interface, and Portuguese falls back to English
because no `pt_BR` translation is shipped. The `zh_Hant` strings stay in the
plugin files and take effect if Dify adds the locale.

Text processing handles Chinese, Japanese, and English, with CJK-aware
sentence splitting and abbreviation protection.

## Effectiveness & Boundaries

This plugin is not a replacement for LLM summarization. It selects source
spans from the original text using extractive summarization, preserving their
original punctuation, whitespace, and line boundaries. It never rewrites or
paraphrases selected text.

### When It Works Well

- **Structured documents** (reports, papers, contracts) where key points are concentrated in topic sentences
- **Dialogue / transcripts** — removing filler and repeated ideas
- **Moderate compression** — enough budget for main points across different sections

### When It Doesn't

- **Narrative / creative text** — information is spread across descriptions
- **Aggressive compression** — any extractive method will lose significant content
- **When you need synthesis** — this tool selects sentences; it cannot merge or rephrase them

## Algorithm

This plugin uses **extractive summarization** — Python standard library only,
no external NLP dependencies. Sentence selection returns original source spans.
If no complete sentence fits the budget, the documented boundary-aware fallback
may cut at punctuation, whitespace, or a hard boundary.

```
Input text → Sentence Split → Score → Select → Reorder by position → Output
```

See [Architecture](https://github.com/AlexMultiAgent/dify-plugin-text-fitter/blob/main/docs/architecture.md)
for the component map, detailed algorithm flow, failure handling, and
performance guarantees.

### Sentence Segmentation

Regex-based sentence splitting aware of CJK, Japanese, and English
punctuation conventions, quoted sentence endings, initialisms (`U.S.`),
personal initials (`John F. Kennedy`), and common abbreviations.

| Language | Sentence-ending markers                        |
| -------- | ---------------------------------------------- |
| Chinese  | `。！？`                                          |
| Japanese | `。！？」』`                                        |
| English  | `. ! ?` followed by uppercase or CJK character |

### Sentence Scoring

```
score = 0.3 × position + 0.5 × keyword_density + 0.2 × length
```

- **Position (0.3):** Intro (first 20%) and conclusion (last 10%) weighted higher.
- **Keyword Density (0.5):** Normalized TF-IDF. Rare tokens get higher weight.
- **Length (0.2):** Penalizes very short (< 10 chars) and very long (> 200 chars) sentences.

### Sentence Selection

Two strategies via the `method` parameter:

**Greedy** — Sort sentences by score descending, pick top ones until the
character budget is exhausted. O(n log n).

**MMR (Maximal Marginal Relevance)** — Iteratively selects sentences that
maximize:

```
MMR = λ × relevance_score + (1 - λ) × (1 − max_token_overlap_with_selected)
```

where λ (`mmr_lambda`) controls the relevance–diversity trade-off:

- λ = 1.0 → pure relevance (same as Greedy)
- λ = 0.7 → moderately favors relevance (default)
- λ = 0.0 → pure diversity (maximum topical variation)

Diversity is measured as token overlap (Jaccard-like) between candidate and
already-selected sentences, updated incrementally per round. O(k × n) overall.

The `algorithm` output variable records which variant was actually used:

| `algorithm` value     | Trigger                            | Behavior                                               |
| --------------------- | ---------------------------------- | ------------------------------------------------------ |
| `passthrough`         | text ≤ max_chars                   | No processing; return original text                    |
| `greedy`              | method = `"greedy"`                | Pure score-ranked selection                            |
| `mmr`                 | method = `"mmr"`, ≤ 5000 sentences | Full MMR on all sentences                              |
| `mmr_prefilter`       | method = `"mmr"`, > 5000 sentences | Pre-filter to top 5000, then MMR, then fill the budget |
| `boundary_truncation` | emergency fallback                 | No sentence fits budget; cut at sentence/word boundary |
| `error_truncation`    | internal error fallback            | Guarantee the output stays within `max_chars`          |

### Reordering & Fallback

Selected sentences are re-sorted by original document order for coherent
output. If no sentence fits within `max_chars`, a boundary-aware fallback
truncates at sentence-ending punctuation → whitespace → hard cut with
ellipsis.

### Complexity

| Metric          | Value                                                                            |
| --------------- | -------------------------------------------------------------------------------- |
| Worst-case time | O(k × n) for MMR, O(n log n) for Greedy (n = candidates, k = selected sentences) |
| Space           | O(n)                                                                             |
| Dependencies    | None (Python stdlib only)                                                        |

## Privacy

This plugin processes all text locally. No data is transmitted to external
servers, APIs, or third-party services. See
[PRIVACY.md](https://github.com/AlexMultiAgent/dify-plugin-text-fitter/blob/main/PRIVACY.md)
for details.

## Changelog

### 0.0.2

- **Selected text is now returned verbatim.** The previous release rewrote the
  input while splitting it — inserting newlines after sentence-ending
  punctuation and stripping whitespace. Sentences are now located by offset, so
  punctuation, spacing, and line boundaries are preserved exactly.
- **Sentence segmentation covers more cases**: closing quotes and brackets,
  initialisms (`U.S.`), personal initials (`John F. Kennedy`), decimal numbers
  (`3.14`), and CRLF line endings.
- **The internal-error fallback honours `max_chars`** instead of returning the
  untrimmed input, and no longer exposes the traceback as an `error` output
  variable.
- **`algorithm` reports one additional outcome**: `error_truncation`.
- **Localization fixes** for the Simplified Chinese, Traditional Chinese, and
  Japanese labels.
- **Packaging hygiene**: development files (`.env.example`, test caches) are no
  longer shipped inside the plugin package.

## Development

```bash
uv sync --locked --group dev
uv run python -m unittest discover -s tests -v
uv run ruff check main.py provider tools tests scripts
uv audit --locked
dify plugin package . -o dist/text_fitter-0.0.2.difypkg
```

The output contract -- "the tool never returns more than `max_chars`
characters, on every path" -- is covered by the unit tests and attacked
with random input by a fuzz target:

```bash
# Linux only: Atheris bundles libFuzzer and ships no Windows/macOS wheel.
uv run --group fuzz python -m tests.fuzz_smart_trim -max_total_time=60
```

New functionality comes with tests. Behaviour changes are covered by a case
in `tests/test_smart_trim.py`, and the output contract is covered by the fuzz
target. `CI` runs the unit tests, the linter, the dependency audit and the
fuzz target on every pull request, and branch protection requires them to
pass before a merge.

## Contributing

Changes reach `main` through a pull request. `main` is protected: the pull
request has to pass the `CI` and `CodeQL` checks, the branch has to be up to
date, and one approving review is required before the pull request can be
merged.

The project is maintained by a single maintainer, so the review requirement
is not enforced against administrators -- otherwise a one-person project
could never merge anything. The maintainer still reviews every change
before merging it, and the CI and CodeQL checks are not bypassable. External
contributions are welcome; open a pull request and it will be reviewed
before it lands.

## Support

GitHub profile: <https://github.com/AlexMultiAgent>

GitHub Issues: <https://github.com/AlexMultiAgent/dify-plugin-text-fitter/issues>

## License

[MIT](https://github.com/AlexMultiAgent/dify-plugin-text-fitter/blob/main/LICENSE)
