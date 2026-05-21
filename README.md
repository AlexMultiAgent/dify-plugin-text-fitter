# Text Fitter — Dify Plugin

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
exceeds a user-configurable threshold, trims it by extracting only the most
informative sentences — before the text ever reaches the LLM.

## What It Does

| Capability | How |
|---|---|
| Measure text length | Outputs `original_char_count` and `processed_char_count` |
| Threshold check | Compares input length against user-configured `max_chars` |
| Smart key-sentence extraction | Built-in extractive summarization (see algorithm below) |
| Passthrough | Returns text unchanged when within limits |
| Language auto-detection | Recognizes Chinese, Japanese, and English; no manual selection needed |

The character threshold `max_chars` is set by the user when adding the tool
to a workflow — not hardcoded. Tune it for your specific model and deployment.

## Language Support

The tool automatically handles **Chinese**, **Japanese**, and **English** text
without any language selector parameter. The tokenizer recognizes:

- **CJK Unified Ideographs** (U+4E00–U+9FFF) — covers Chinese *kanji* / Japanese *kanji*
- **CJK Extension A** (U+3400–U+4DBF) — rare and historical characters
- **Hiragana** (U+3040–U+309F) — Japanese syllabary
- **Katakana** (U+30A0–U+30FF) — Japanese syllabary
- **Latin words** — extracted via word-boundary regex (`[a-zA-Z0-9]+`)

The sentence splitter likewise handles CJK fullwidth punctuation (`。！？；`)
alongside English halfwidth punctuation (`. ! ?`), so mixed-language documents
are segmented correctly.

## Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | Yes | — | Input text to process |
| `max_chars` | number | Yes | 30000 | Character threshold; exceeding triggers trimming |

## Outputs

| Output | Type | Description |
|---|---|---|
| `processed_text` | string | The processed text (original or trimmed). |
| `original_char_count` | number | Character count of the original input text. |
| `processed_char_count` | number | Character count of the output text. |
| `was_trimmed` | boolean | Whether the text was trimmed (true if original exceeded max_chars). |

## Smart Key-Sentence Extraction Algorithm

This plugin uses **extractive summarization** — no external NLP dependencies,
pure Python standard library. Works across Chinese, Japanese, and English.

### 1. Sentence Segmentation

Regex-based sentence splitting aware of:

- **CJK fullwidth punctuation**: `。！？；`
- **English halfwidth punctuation**: `. ! ?` followed by a capital letter or CJK character
- **Ellipsis**: `...` (English) and `……` (CJK)
- **Edge cases**: decimal numbers (`3.14`), abbreviations (`Mr.`)

### 2. Sentence Scoring

Each sentence receives a composite score:

```
score = 0.3 × position + 0.5 × keyword_density + 0.2 × length
```

#### Position Score (weight 0.3)

Sentences near the beginning (introduction) and end (conclusion) of a
document tend to carry more weight:

| Position | Score |
|---|---|
| First 20% (intro) | 0.7–1.0 |
| Last 10% (conclusion) | 0.6–1.0 |
| Middle 70% | 0.2–0.5 (linear decay) |

#### Keyword Density Score (weight 0.5)

The core of the algorithm. A lightweight TF (term frequency) analysis:

1. Tokenize the entire document — CJK ideographs and Japanese kana become
   individual character tokens; English words are extracted by word-boundary
   regex. Language detection is implicit in the Unicode ranges, so mixed
   Chinese/Japanese/English text is handled without configuration.
2. Build a global word-frequency counter.
3. For each sentence, compute the average frequency of its constituent tokens.
4. Sentences rich in high-frequency tokens score higher — they are more
   representative of the document's subject matter.

This works without dictionaries or pre-trained models.

#### Length Score (weight 0.2)

| Length | Score | Rationale |
| --- | --- | --- |
| < 10 chars | 0.15 | Too short (filler / transition) |
| 10–20 chars | 0.50 | On the short side |
| 20–150 chars | 0.90–1.00 | Ideal information density |
| 150–200 chars | 0.60 | Getting verbose |
| > 200 chars | 0.30 | Overly dense |

### 3. Greedy Selection

Sort all sentences by composite score (descending). Pick sentences one by one
until the cumulative character count reaches `max_chars`.

### 4. Positional Reordering

Selected sentences are re-sorted by their original order in the text, so the
output remains coherent and readable.

### Complexity

| Metric | Value |
|---|---|
| Time | O(n log n), where n = number of sentences |
| Space | O(n) |
| Dependencies | None (Python stdlib only) |

## Usage

1. Install the plugin into your Dify workspace.
2. In a workflow, add the **Smart Trim** node.
3. Wire `text` to your upstream content source (document parser, HTTP input, etc.).
4. Set `max_chars` to a value below your LLM's actual context limit.
5. Connect the node's text output to your downstream LLM node.
6. Optionally use `was_trimmed` to branch logic (e.g. log a warning when trimming occurred).

### Choosing max_chars

A conservative rule of thumb: set `max_chars` to ~80% of the token limit for
your model. For example, if your serving parameters specify
`--max-model-len 25000`, try `max_chars: 20000` as a starting point. Adjust
based on observed behavior with your specific workload.

## License

MIT
