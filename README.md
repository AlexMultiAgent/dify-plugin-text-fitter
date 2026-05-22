# Text Fitter

A Dify tool plugin that ensures text fits within LLM context window limits
via intelligent extractive summarization. Supports **Chinese**, **Japanese**,
and **English** text.

## Why

Locally deployed or resource-constrained LLM instances often have a smaller
effective context window than the model's official specification — due to
hardware limits (GPU VRAM), concurrency requirements, or serving parameters
like `--max-model-len`. When input text exceeds the window, the LLM fails
with a context-length error.

This plugin acts as a pre-processing guard: it measures the input, and if it
exceeds a user-configured threshold, trims it by extracting only the most
informative sentences — before the text ever reaches the LLM.

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
3. Set `max_chars` to a value below your LLM's actual context limit.
4. Connect the node's text output to your downstream LLM node.
5. Optionally use `was_trimmed` to branch logic (e.g., log a warning when trimming occurred).

### Choosing max_chars

`max_chars` is a **character count** threshold. The plugin simply checks
`len(input)`: if the character count exceeds `max_chars`, it trims the text;
otherwise it passes through unchanged. It does NOT measure tokens or know
anything about your model's tokenizer.

To pick a value, translate your target token budget into a character limit
based on your primary input language. The ratios below are based on the
**Qwen3 tokenizer** (BBPE, 151K vocab) — representative of modern Chinese
LLM tokenizers:

| Language | Tokens per char | How many chars fit in 20K tokens |
| --- | --- | --- |
| English | ~0.25 (1 token ≈ 4 chars) | ~80,000 |
| Chinese | ~0.6 (1 token ≈ 1.7 chars) | ~33,000 |
| Japanese | ~0.8 (1 token ≈ 1.3 chars) | ~25,000 |

> **Note:** Token-to-character ratios vary across model families. The table
> above reflects Qwen3 (BBPE, 151K vocab). GPT-4 class tokenizers (cl100k)
> consume ~1.1 tokens per Chinese character — nearly 2× more. Always verify
> with your specific model's tokenizer when precise budgeting is critical.
>
> Sources: Qwen3 Technical Report (arXiv:2505.09388, 2025); TokLens
> (ACL 2026 SRW).

For a model with `--max-model-len 25000` (25K tokens), reserving ~80% (~20K
tokens) for input text is recommended — the remaining ~20% (~5K tokens) should
be kept for the LLM node's prompt template, instructions, and output generation.
At this budget:

- English → `max_chars: 80000`
- Chinese → `max_chars: 33000`
- Japanese → `max_chars: 25000`

Choose a value that suits your expected input, then adjust after observing
actual behavior.

## Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | Yes | — | Input text to process |
| `max_chars` | number | Yes | 30000 | Character threshold; exceeding triggers trimming |
| `method` | select | No | `mmr` | Sentence selection: `"mmr"` (diverse, O(n²)) or `"greedy"` (fast, O(n log n)) |
| `mmr_lambda` | select | No | `0.7` | MMR λ (relevance weight). 11 options from `0.0` (Pure Diversity) to `1.0` (Pure Relevance). Ignored when `method` is `"greedy"` |

## Outputs

| Output | Type | Description |
|---|---|---|
| `text` | string | The processed text (original or trimmed) |
| `original_char_count` | number | Character count of the original input text |
| `processed_char_count` | number | Character count of the output text |
| `was_trimmed` | boolean | Whether the text was trimmed (true if original exceeded max_chars) |

## Language Support

The tool automatically handles **Chinese**, **Japanese**, and **English** text
without any language selector parameter. The tokenizer recognizes:

- **CJK Unified Ideographs** (U+4E00–U+9FFF) — Chinese and Japanese kanji
- **CJK Extension A** (U+3400–U+4DBF) — rare and historical characters
- **Hiragana** (U+3040–U+309F) — Japanese syllabary
- **Katakana** (U+30A0–U+30FF) — Japanese syllabary
- **Latin words** — extracted via word-boundary regex (`[a-zA-Z0-9]+`)

The sentence splitter handles CJK fullwidth punctuation (`。！？`),
Japanese closing brackets (`」』`), English halfwidth punctuation (`. ! ?`),
ellipsis (`...` / `……`), and common abbreviations (`Mr.`, `Dr.`, etc.).

## Algorithm

This plugin uses **extractive summarization** — no external NLP dependencies,
pure Python standard library.

### 1. Sentence Segmentation

Regex-based sentence splitting aware of CJK, Japanese, and English
punctuation conventions, with abbreviation protection.

### 2. Sentence Scoring

```
score = 0.3 × position + 0.5 × keyword_density + 0.2 × length
```

- **Position Score (0.3):** Intro and conclusion sentences weighted higher.
- **Keyword Density (0.5):** Normalized TF-IDF analysis, penalizing
  function words (的/the/は) that appear across documents.
- **Length Score (0.2):** Penalizes very short (< 10 chars, likely filler)
  and very long (> 200 chars, likely verbose) sentences.

### 3. Sentence Selection

Two strategies via the `method` parameter:

- **Greedy** (`method = "greedy"`): Top-score selection, O(n log n). Fast.
- **MMR** (`method = "mmr"`): Maximal Marginal Relevance balancing
  relevance with diversity: `MMR = λ × relevance + (1 - λ) × diversity`.
  O(n²), but produces less redundant summaries.

### 4. Positional Reordering

Selected sentences are re-sorted by original order for coherent output.

### 5. Boundary-Aware Fallback

If no sentence fits within `max_chars`, falls back to sentence-boundary
truncation, then whitespace, then hard truncation with ellipsis.

### Complexity

| Metric | Value |
|---|---|
| Time | O(n²) for MMR, O(n log n) for greedy (n = number of sentences) |
| Space | O(n) |
| Dependencies | None (Python stdlib only) |

## Privacy

This plugin processes all text locally. No data is transmitted to external
servers, APIs, or third-party services. See [PRIVACY.md](PRIVACY.md) for details.

## License

[MIT](LICENSE)
