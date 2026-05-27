# Text Fitter

A Dify tool plugin that ensures text fits within LLM context window limits
via intelligent extractive summarization. Supports Chinese (Simplified &
Traditional), Japanese, and English text.

## Why

Locally deployed or resource-constrained LLM instances often have a smaller
effective context window than the model's official specification — due to
hardware limits (GPU VRAM), concurrency requirements, or serving parameters
like `--max-model-len`. When input text exceeds the window, the LLM fails
with a context-length error.

This plugin acts as a pre-processing guard: it measures the input, and if it
exceeds a user-configured threshold, trims it by extracting only the
highest-scoring sentences — before the text ever reaches the LLM. No API
keys, no network calls, no external dependencies.

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

Reserve ~80% of the context window for input text, leaving headroom for
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

The plugin interface supports four locales:

| Locale    | Language            |
| --------- | ------------------- |
| `en_US`   | English             |
| `zh_Hans` | Simplified Chinese  |
| `zh_Hant` | Traditional Chinese |
| `ja_JP`   | Japanese            |

All parameter labels, descriptions, and option values are translated across
the supported locales.
Text processing handles Chinese, Japanese, and English, with CJK-aware
sentence splitting and abbreviation protection.

## Effectiveness & Boundaries

This plugin is not a replacement for LLM summarization. It selects complete
verbatim sentences from the original text using extractive summarization, a
long-established NLP approach — it never rewrites or paraphrases.

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
no external NLP dependencies. It selects complete sentences from the original
text; it never rewrites, paraphrases, or cuts mid-sentence.

```
Input text → Sentence Split → Score → Select → Reorder by position → Output
```

### Sentence Segmentation

Regex-based sentence splitting aware of CJK, Japanese, and English
punctuation conventions, with abbreviation protection.

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

| `algorithm` value     | Trigger                            | Behavior                                                 |
| --------------------- | ---------------------------------- | -------------------------------------------------------- |
| `passthrough`         | text ≤ max_chars                   | No processing; return original text                      |
| `greedy`              | method = `"greedy"`                | Pure score-ranked selection                              |
| `mmr`                 | method = `"mmr"`, ≤ 5000 sentences | Full MMR on all sentences                                |
| `mmr_prefilter`       | method = `"mmr"`, > 5000 sentences | Score-ranked pre-filter to top 5000 candidates, then MMR |
| `boundary_truncation` | emergency fallback                 | No sentence fits budget; cut at sentence/word boundary   |

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
servers, APIs, or third-party services. See [PRIVACY.md](PRIVACY.md) for details.

## Support

GitHub profile: <https://github.com/AlexMultiAgent>

GitHub Issues: <https://github.com/AlexMultiAgent/dify-plugin-text-fitter/issues>

## License

[MIT](LICENSE)
