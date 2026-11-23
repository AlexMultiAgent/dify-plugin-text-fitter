# Text Fitter

Dify tool plugin that trims text to fit an LLM context window. One tool
(`smart_trim`), no credentials, no network, Python stdlib only.

## Commands

| Command | Purpose |
|---|---|
| `uv sync --locked --group dev` | Install locked deps (CI uses `--locked --group dev`) |
| `uv run python -m unittest discover -s tests -v` | 18 unit tests |
| `uv run ruff check main.py provider tools tests` | Lint |
| `uv run ruff format --check main.py provider tools tests` | Format check (CI gate) |
| `uv audit --locked` | Dependency audit |
| `uv run --group fuzz python -m tests.fuzz_smart_trim -max_total_time=60` | Fuzz the output contract (Linux only) |
| `dify plugin package . -o dist/text_fitter-<version>.difypkg` | Build marketplace package |

No ruff config exists — ruff runs on defaults (88 columns).

Ruff and pip-audit live in the `dev` dependency group, so `uv run ruff` uses the
locked version instead of floating on the latest release the way `uvx ruff`
does. Dependabot manages that group; `dify-plugin` is excluded from it because
the plugin daemon installs it from its own lagging package mirror.

Atheris lives in a separate `fuzz` group: it bundles libFuzzer and ships
Linux-only wheels, so `uv sync --group dev` has to keep installing on Windows
and macOS. The fuzz target runs in its own CI job on ubuntu-latest.

## Architecture

```
manifest.yaml              # version + meta.version, repo/contact/tags
main.py                    # entrypoint: Plugin(DifyPluginEnv()).run()
provider/text_fitter.yaml  # provider identity, lists the tool
provider/text_fitter.py    # ToolProvider; _validate_credentials is a no-op
tools/smart_trim.yaml      # tool schema: parameters + output_schema
tools/smart_trim.py        # the entire implementation
tests/test_smart_trim.py   # regression tests
tests/fuzz_smart_trim.py   # atheris fuzz target for the output contract
docs/architecture.md       # component map + algorithm flow (Mermaid)
```

Invocation: `_invoke` → `_do_invoke` (normalizes `max_chars`/`method`/`mmr_lambda`)
→ `_extract_key_sentences` → `_split_sentences` → `_score_sentences` →
`_greedy_select` | `_mmr_select` → `_yield_outputs` (1 text + 5 variable + 1 JSON
message).

## Gotchas

**Packaging.** `.difyignore` alone decides what ships. It must keep `dist/`,
`docs/`, `tests/`, `*.difypkg`, `.env.example` and caches out — a scratch file
left in `dist/` lands in the release. Verify after every build:

```bash
python -c "import zipfile; print(zipfile.ZipFile('dist/<pkg>.difypkg').namelist())"
```

**Version bumps.** `pyproject.toml`'s version is mirrored into `uv.lock`; bump
one without the other and CI fails at `uv sync --locked`. `manifest.yaml`
carries the version twice (`version` and `meta.version`) — both must change.

**Marketplace manifest fields.** `repo` (URL on github.com et al.) and `contact`
(email) are mandatory in `manifest.yaml`; `meta.minimum_dify_version` is
recommended. Missing `repo`/`contact` fails the marketplace validator.

**Dify parameter `form`.** `form: llm` renders under "Input Variables" in the
workflow node (the wireable input); `form: form` renders under "Settings".
`text` is `llm`; `max_chars`, `method`, `mmr_lambda` are `form`. The SDK's
`ToolParameterForm` enum has no `llm+form` value — a parameter is one or the
other, never both.

**Plugin locales.** The Dify plugin manifest format carries only `en_US`,
`zh_Hans`, `ja_JP` and `pt_BR`. The SDK's `I18nObject` drops every other key
silently, so the `zh_Hant` strings in the YAML files are never rendered today —
they are kept so they take effect if Dify adds the locale, and a typo in a
locale key would drop a whole language without any error (a test guards the
key set). Check the SDK and the daemon before promising a new interface
locale. A new *processing* language — splitting, tokenizing, scoring — is
independent of this and needs no locale support at all.

**The output contract is the guarantee.** Output must never exceed `max_chars`,
including on the internal-error path: that path truncates and reports
`algorithm=error_truncation`, and must not leak the traceback as an output
variable. Emit exactly one JSON message — Dify treats every JSON message as a
separate output. The six output variables are `text`, `original_char_count`,
`processed_char_count`, `compression_ratio`, `was_trimmed`, `algorithm`
(`passthrough` | `greedy` | `mmr` | `mmr_prefilter` | `boundary_truncation` |
`error_truncation`).

**Sentence splitting must not rewrite the input.** Boundaries are located by
offset; the protected copy swaps `.` for `\x00` in a same-length copy so offsets
map 1:1 back to the original. The 0.0.1 build inserted newlines after
sentence-ending punctuation and stripped whitespace, so it returned text the
caller never sent.

## Releasing

1. Bump `version` in `manifest.yaml` (both fields) and `pyproject.toml`, update
   the version referenced in `docs/architecture.md`, add a `README.md` changelog
   entry. Stay in the `0.0.x` patch series.
2. `uv lock` — the lockfile embeds the project version.
3. `dify plugin package . -o dist/text_fitter-<version>.difypkg`, then verify
   the file list.
4. Pre-flight the marketplace validators (needs `yq` on PATH):
   ```bash
   git clone --depth 1 https://github.com/langgenius/dify-marketplace-toolkit
   cd dify-marketplace-toolkit
   python validator/validate-difypkg.py <abs-path-to-pkg> --toolkit-dir . \
     --pr-body-file <pr-body.md> --output-dir <out>
   ```
5. Tag the commit and publish the GitHub Release with the `.difypkg` asset and
   its SHA256.
6. PR to `langgenius/dify-plugins`: change exactly one `.difypkg` (removing older
   versions in the same directory is allowed), named `<plugin>-<version>.difypkg`.
   The body follows that repo's PR template and must be English-only, with
   `## Plugin information`, `## Submission type`, `## Risk level`,
   `## What changed` and `## Local validation` filled in.
