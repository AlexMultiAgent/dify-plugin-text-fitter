# Text Fitter

A Dify tool plugin that ensures text fits within LLM context window limits
via intelligent extractive summarization. Supports **Chinese** (Simplified & Traditional), **Japanese**,
and **English** text. UI localized in **English**, **Simplified Chinese**,
**Traditional Chinese**, and **Japanese**.

## Why

Locally deployed or resource-constrained LLM instances often have a smaller
effective context window than the model's official specification — due to
hardware limits (GPU VRAM), concurrency requirements, or serving parameters
like `--max-model-len`. When input text exceeds the window, the LLM fails
with a context-length error.

This plugin acts as a pre-processing guard: it measures the input, and if it
exceeds a user-configured threshold, trims it by extracting only the most
informative sentences — before the text ever reaches the LLM.

> **Source**: [github.com/AlexMultiAgent/dify-plugin-text-fitter](https://github.com/AlexMultiAgent/dify-plugin-text-fitter)

## Requirements

- **No API keys or credentials** — the plugin runs entirely in-process with no external services.
- **No network connection** — all processing is local and in-memory.
- Dify platform (Community Edition or Cloud) with plugin support enabled.

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

`max_chars` is a **character count** threshold — the plugin checks `len(input)`
against it. If the count exceeds `max_chars`, the text is trimmed; otherwise it
passes through unchanged. It does not measure tokens.

To pick a value, translate your target token budget into a character limit
based on your primary input language. The ratios below are based on the
**Qwen3 tokenizer** (BBPE, 151K vocab) — representative of modern Chinese
LLM tokenizers:

| Language | Tokens per char            | How many chars fit in 20K tokens |
| -------- | -------------------------- | -------------------------------- |
| English  | ~0.25 (1 token ≈ 4 chars)  | ~80,000                          |
| Chinese  | ~0.6 (1 token ≈ 1.7 chars) | ~33,000                          |
| Japanese | ~0.8 (1 token ≈ 1.3 chars) | ~25,000                          |

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

| Parameter    | Type   | Required | Default | Description                                                                                                                     |
| ------------ | ------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `text`       | string | Yes      | —       | Input text to process                                                                                                           |
| `max_chars`  | number | Yes      | 30000   | Character threshold; exceeding triggers trimming                                                                                |
| `method`     | select | No       | `mmr`   | Sentence selection: `"mmr"` (diverse, O(k×n)) or `"greedy"` (fast, O(n log n))                                                  |
| `mmr_lambda` | select | No       | `0.7`   | MMR λ (relevance weight). 11 options from `0.0` (Pure Diversity) to `1.0` (Pure Relevance). Ignored when `method` is `"greedy"` |

## Outputs

| Output                 | Type    | Description                                                                        |
| ---------------------- | ------- | ---------------------------------------------------------------------------------- |
| `text`                 | string  | The processed text (original or trimmed)                                           |
| `original_char_count`  | number  | Character count of the original input text                                         |
| `processed_char_count` | number  | Character count of the output text                                                 |
| `was_trimmed`          | boolean | Whether the text was trimmed (true if original exceeded max_chars)                 |
| `compression_ratio`    | number  | Compression ratio (original / processed). 1.0 when not trimmed, > 1.0 when trimmed |
| `algorithm`            | string  | Algorithm actually used. See [Algorithm](#algorithm) for details                   |

## Language Support

### Text Processing

The tool handles **Chinese** (Simplified & Traditional), **Japanese**,
and **English** text. The tokenizer recognizes:

- **CJK Unified Ideographs** (U+4E00–U+9FFF) — Chinese and Japanese kanji
- **CJK Extension A** (U+3400–U+4DBF) — rare and historical characters
- **CJK Compatibility Ideographs** (U+F900–U+FAFF) — legacy encodings
- **CJK Extensions B–I** (U+20000–U+2EBEF) — supplementary plane characters
- **Hiragana** (U+3040–U+309F) — Japanese syllabary
- **Katakana** (U+30A0–U+30FF) — Japanese syllabary
- **Halfwidth Katakana** (U+FF65–U+FF9F) — Japanese halfwidth forms
- **Latin words** — extracted via word-boundary regex (`[a-zA-Z0-9]+`)

### UI Localization

The plugin interface supports four locales:

| Locale    | Language            |
| --------- | ------------------- |
| `en_US`   | English             |
| `zh_Hans` | Simplified Chinese  |
| `zh_Hant` | Traditional Chinese |
| `ja_JP`   | Japanese            |

All parameter labels, descriptions, and option values are fully translated.

The sentence splitter handles CJK fullwidth punctuation (`。！？`),
Japanese closing brackets (`」』`), English halfwidth punctuation (`. ! ?`),
ellipsis (`...` / `……`), and common abbreviations (`Mr.`, `Dr.`, etc.).

## Effectiveness & Boundaries

This plugin is **not a replacement for LLM summarization**. It is designed
for a specific scenario:

> You need **original text** inside the LLM context window, but the document
> is too long to fit. You want to cut redundant parts while preserving as
> many diverse, information-rich **verbatim sentences** as possible.

### Comparison with LLM Summarization

| Aspect             | Text Fitter (this plugin)                                         | LLM Summarization                                      |
| ------------------ | ----------------------------------------------------------------- | ------------------------------------------------------ |
| **Output**         | Original sentences, verbatim                                      | Rewritten abstract                                     |
| **Fidelity**       | High — no paraphrasing or hallucination risk                      | May introduce generalization errors                    |
| **Coverage**       | Limited to what existing sentences express                        | Can fuse information across sentences                  |
| **Token cost**     | Zero (runs before LLM)                                            | Consumes input + output tokens                         |
| **Context window** | Compression runs outside the LLM; output still uses context space | Must fit the full document **plus** the summary output |
| **Speed**          | Under 3 seconds for most documents     | Model-dependent (seconds to minutes)                   |
| **Language**       | Chinese / Japanese / English                                      | Model-dependent                                        |

### When It Works Well

- **Structured documents** (reports, papers, contracts) where key points are
  concentrated in topic sentences
- **Moderate compression** — enough budget for the main points across
  different sections
- **Dialogue / transcripts** — removing filler and repeated ideas, keeping
  the substantive turns

### When It Doesn't

- **Narrative / creative text** — information is spread across descriptions,
  not concentrated in individual sentences
- **Aggressive compression** — any extractive method will lose
  significant content
- **When you need synthesis** — this tool selects sentences; it cannot merge
  or rephrase them

### Practical Advice

Give the plugin a generous budget — **70–80% of the LLM's effective context
window**. The diversity mechanism (MMR) works best when it has room to cover
different facets of the document. Overly tight budgets force it to pick only
the highest-scoring sentences, which tend to be thematically similar.

Research on MMR specifically (not general extractive methods) confirms its
effectiveness. On Chinese news texts (NLPCC2017), an MMR-based summarizer
achieved ROUGE-1 77.8%, ROUGE-2 60.3%, ROUGE-L 63.9% — outperforming
both TextRank (+3 pp) and Lead-3 (+2 pp) baselines [1]. The optimal λ was
found to be **0.7** for Chinese text. (This plugin uses the same λ, though
the paper used neural embeddings while this plugin uses TF-IDF — the
optimal value may differ.) On English CNN/Daily Mail, a 2026 study explicitly validated
diversity penalties for extractive summarization: the DiCo-EXT framework
achieved lower redundancy (Self-BLEU) without sacrificing ROUGE by adding a
differentiable diversity loss — the same principle behind MMR [2]. DL-MMR (NAACL 2025) preserved MMR's informativeness
while reducing computation by 500,000× [3]. For Japanese, MMR with
doc2vec embeddings on Nikkei news achieved ~27% content-level agreement
with human-written summaries, and outputs diverging from the reference were also judged plausible [4]; MMR combined with NMT embeddings on
Japanese lecture transcripts outperformed baselines by over 20% [5].

> These benchmarks use neural embeddings (Word2Vec / BERT) for sentence
> representation, not pure TF-IDF. The ROUGE scores above reflect
> research-grade implementations and should not be read as this plugin's
> expected scores. This plugin's heuristic scoring (position + keyword
> density + length) is simpler; the diversity mechanism provides the same
> structural benefit, but absolute output quality will be lower. Cited
> benchmarks span **English, Chinese, and Japanese** datasets (CNN/Daily
> Mail, NLPCC2017, Nikkei, TED transcripts).

MMR's diversity penalty reduces redundancy regardless of compression ratio.
The practical ceiling is simple: the output can only hold as many sentences
as fit within `max_chars`. At the default `max_chars = 30000` (~500–600 Chinese sentences),
about one-third of sentences survive for a ~100K character document.

At the same time, the remaining 20–30% headroom is essential for the downstream
workflow: the LLM node's prompt template, system instructions, and output
tokens all consume the same context window. If `max_chars` occupies the entire
window, the combined length of prompt + trimmed text + generated response will
still exceed the model's limit and cause a context-length error. The plugin
only controls the input text portion — it cannot see or account for the rest
of the pipeline.

## Algorithm

This plugin uses **extractive summarization** — pure Python standard library,
no external NLP dependencies. It selects complete sentences from the original
text; it never rewrites, paraphrases, or cuts mid-sentence (outside the
boundary-aware fallback).

### Pipeline

```
Input text → Sentence Split → Score → Select → Reorder by position → Output
```

### 1. Sentence Segmentation

Regex-based sentence splitting aware of CJK, Japanese, and English
punctuation conventions, with abbreviation protection for 40+ common
abbreviations (`Mr.`, `Dr.`, `Inc.`, etc.).

| Language | Sentence-ending markers                        |
| -------- | ---------------------------------------------- |
| Chinese  | `。！？`                                          |
| Japanese | `。！？」』`                                        |
| English  | `. ! ?` followed by uppercase or CJK character |

### 2. Sentence Scoring

```
score = 0.3 × position + 0.5 × keyword_density + 0.2 × length
```

- **Position Score (0.3):** Intro (first 20%) and conclusion (last 10%) weighted
  higher; middle sections decay linearly.
- **Keyword Density (0.5):** Normalized TF-IDF. Tokens rare across the document
  get higher weight; frequent function words that appear everywhere are
  naturally downweighted.
- **Length Score (0.2):** Penalizes very short (< 10 chars, likely filler) and
  very long (> 200 chars, likely verbose) sentences. Sweet spot: 20–150 chars.

### 3. Sentence Selection

Two strategies via the `method` parameter:

**Greedy** — Sort sentences by score descending, pick top ones until the
character budget is exhausted. O(n log n). Fast and predictable.

**MMR (Maximal Marginal Relevance)** — Iteratively selects sentences that
maximize:

```
MMR = λ × relevance_score + (1 - λ) × (1 − max_token_overlap_with_selected)
```

where λ (`mmr_lambda`) controls the relevance–diversity trade-off:

- λ = 1.0 → pure relevance (same behavior as Greedy)
- λ = 0.7 → moderately favors relevance (default, recommended)
- λ = 0.0 → pure diversity (maximum topical variation)

Diversity is measured as token overlap (Jaccard-like) between candidate and
already-selected sentences. Tracking is incremental — each candidate's max
overlap is updated against only the newly-selected sentence per round, giving
O(k × n) overall complexity.

**Performance guardrails** — The `algorithm` output variable records which
variant was actually used:

| `algorithm` value     | Trigger                            | Behavior                                                 |
| --------------------- | ---------------------------------- | -------------------------------------------------------- |
| `passthrough`         | text ≤ max_chars                   | No processing; return original text                      |
| `greedy`              | method = `"greedy"`                | Pure score-ranked selection                              |
| `mmr`                 | method = `"mmr"`, ≤ 5000 sentences | Full MMR on all sentences                                |
| `mmr_prefilter`       | method = `"mmr"`, > 5000 sentences | Score-ranked pre-filter to top 5000 candidates, then MMR |
| `boundary_truncation` | emergency fallback                 | No sentence fits budget; cut at sentence/word boundary   |

### 4. Positional Reordering

Selected sentences are re-sorted by their original document order for
coherent, readable output.

### 5. Boundary-Aware Fallback

Triggered only when no sentence fits within `max_chars` (e.g., every sentence
is individually longer than the budget). Tries: sentence-ending punctuation →
whitespace boundary → hard truncation with ellipsis (`...` for English text,
`……` for CJK text).

### Complexity

| Metric          | Value                                                                            |
| --------------- | -------------------------------------------------------------------------------- |
| Worst-case time | O(k × n) for MMR, O(n log n) for Greedy (n = candidates, k = selected sentences) |
| Space           | O(n)                                                                             |
| Dependencies    | None (Python stdlib only)                                                        |

## Privacy

This plugin processes all text locally. No data is transmitted to external
servers, APIs, or third-party services. See [PRIVACY.md](PRIVACY.md) for details.

## License

[MIT](LICENSE)

## References

1. Zhang, Q., Fan, Y., & Jin, D. (2023). *Research on News Text Summarization Generation Based on MMR and WordNet.* Journal of Southwest China Normal University.
2. Wang, Y. & Zhang, J. (2026). *DiCo-EXT: Diversity and Consistency-Guided Framework for Extractive Summarization.* MDPI Entropy, 28(1), 88.
3. Juseon-Do et al. (2025). *Considering Length Diversity in Retrieval-Augmented Summarization.* In Findings of the Association for Computational Linguistics: NAACL 2025.
4. Ishihara, S. & Sawa, N. (2021). *News Article Summarization Using MMR-based Sentence Selection and TF-IDF-based Sentence Compression.* In Proceedings of the 35th Annual Conference of the Japanese Society for Artificial Intelligence (JSAI 2021).
5. ANLP 2020 (P5-21). *MMR with NMT/BERT Distributed Representations for Lecture Transcript Summarization.* In Proceedings of the 26th Annual Meeting of the Association for Natural Language Processing.
