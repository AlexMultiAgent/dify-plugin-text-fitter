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
exceeds a user-configured threshold, trims it by extracting only the most
informative sentences — before the text ever reaches the LLM.

## What It Does

| Capability | How |
|---|---|
| Measure text length | Outputs `original_char_count` and `processed_char_count` |
| Threshold check | Compares input length against user-configured `max_chars` |
| Smart key-sentence extraction | Built-in extractive summarization (see algorithm below) |
| Passthrough | Returns text unchanged when within limits |
| Language auto-detection | Recognizes Chinese, Japanese, and English; no manual selection needed |
| Diversity-aware selection | MMR algorithm reduces redundant sentences in the output |

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

The sentence splitter likewise handles CJK fullwidth punctuation (`。！？`),
Japanese closing brackets (`」』`), English halfwidth punctuation (`. ! ?`),
ellipsis (`...` / `……`), and common abbreviations (`Mr.`, `Dr.`, etc.),
so mixed-language documents are segmented correctly.

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
| `text` | string | The processed text (original or trimmed). |
| `original_char_count` | number | Character count of the original input text. |
| `processed_char_count` | number | Character count of the output text. |
| `was_trimmed` | boolean | Whether the text was trimmed (true if original exceeded max_chars). |

## Smart Key-Sentence Extraction Algorithm

This plugin uses **extractive summarization** — no external NLP dependencies,
pure Python standard library. Works across Chinese, Japanese, and English.

### 1. Sentence Segmentation

Regex-based sentence splitting aware of:

- **CJK fullwidth punctuation**: `。！？` (note: `；` is excluded as it separates clauses, not sentences)
- **Japanese closing brackets**: `」』`
- **English halfwidth punctuation**: `. ! ?` followed by a capital letter or CJK character
- **Ellipsis**: `...` (English, 3+ dots) and `……` (CJK, 2+ `…` characters)
- **Abbreviation protection**: Known abbreviations like `Mr.`, `Dr.`, `Inc.`, `etc.` are protected from being incorrectly split as sentence boundaries

### 2. Sentence Scoring

Each sentence receives a composite score:

```
score = 0.3 × position + 0.5 × keyword_density + 0.2 × length
```

#### Position Score (weight 0.3)

Sentences near the beginning (introduction) and end (conclusion) of a
document carry more weight. The function is continuous across the full range:

| Position | Score Range |
|---|---|
| First 20% (intro) | 1.0 → 0.7 |
| Middle 70% | 0.7 → 0.2 (linear decay) |
| Last 10% (conclusion) | 0.2 → 1.0 |

#### Keyword Density Score (weight 0.5) — Normalized TF-IDF

The core of the algorithm. A lightweight TF-IDF (term frequency — inverse
document frequency) analysis, **normalized by unique token count** to prevent
bias toward sentences with larger vocabulary:

1. Tokenize the entire document — CJK ideographs and Japanese kana become
   individual character tokens; English words are extracted by word-boundary
   regex. Language detection is implicit in the Unicode ranges, so mixed
   Chinese/Japanese/English text is handled without configuration.
   Each sentence is tokenized only once; results are cached for the scoring
   phase.
2. Build a document-frequency (DF) counter — records how many sentences each
   token appears in.
3. For each sentence, compute a TF-IDF score:
   - **TF** (term frequency): token count within the sentence ÷ sentence length.
     Rewards sentences where a topic word is prominent.
   - **IDF** (inverse document frequency): `log(total_sentences / df) + 1`.
     Penalizes tokens that appear in nearly every sentence (function words like
     的 / the / は) and rewards discriminative content words.
   - Final score = Σ (TF × IDF) ÷ unique_token_count.
     Normalization prevents long sentences with many distinct tokens from
     dominating simply due to vocabulary size.
4. Sentences rich in high-TF-IDF tokens score higher — they carry the
   document's distinctive subject matter rather than generic filler.

This works without dictionaries, pre-trained models, or external NLP
dependencies.

#### Length Score (weight 0.2)

| Length | Score | Rationale |
| --- | --- | --- |
| < 10 chars | 0.15 | Too short (filler / transition) |
| 10–20 chars | 0.50 | On the short side |
| 20–150 chars | 0.90–1.00 | Ideal information density |
| 150–200 chars | 0.60 | Getting verbose |
| > 200 chars | 0.30 | Overly dense |

### 3. Sentence Selection

Two selection strategies are available via the `method` parameter:

#### Greedy Selection (`method = "greedy"`, default)

Simple top-score selection — sentences are sorted by composite score
descending and added until the character budget is exhausted.

- **Speed**: O(n log n) — fast path for large documents or when diversity
  is not critical.
- **Trade-off**: May select multiple sentences covering the same topic,
  producing a more repetitive summary.

#### MMR Selection (`method = "mmr"`)

Maximal Marginal Relevance balances relevance with diversity:

```
MMR = λ × relevance + (1 - λ) × diversity
```

- **Relevance**: the sentence's composite score (position + keyword + length).
- **Diversity**: `1 - max_overlap_ratio` with already-selected sentences,
  measured by token overlap.
- **λ (lambda)**: configurable via `mmr_lambda` parameter (default 0.7,
  favoring relevance moderately). Set to 1.0 for pure relevance (equivalent
  to greedy), or 0.0 for pure diversity.
- **Speed**: O(n²) — slower but produces a more informative, less redundant
  summary.

This prevents selecting multiple sentences that say the same thing, producing
a more informative and less redundant summary.

### 4. Positional Reordering

Selected sentences are re-sorted by their original order in the text, so the
output remains coherent and readable.

### 5. Boundary-Aware Fallback Truncation

If no individual sentence fits within `max_chars` (e.g., the input is one
giant paragraph), the algorithm falls back to **boundary-aware truncation**:

1. Find the last sentence-ending punctuation within the budget (keeping at
   least 50% of the text).
2. If no punctuation is found, truncate at the last whitespace boundary.
3. Last resort: hard truncation with an ellipsis (`...`) indicator.

This ensures the output never ends mid-word or mid-sentence when possible.

### Complexity

| Metric | Value |
|---|---|
| Time | O(n²) for MMR selection, O(n log n) for scoring, where n = number of sentences |
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
