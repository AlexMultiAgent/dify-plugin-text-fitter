# Text Fitter

Dify tool plugin that trims text to fit an LLM context window. One tool
(`smart_trim`), no credentials, no network, Python stdlib only.

## Commands

| Command | Purpose |
|---|---|
| `uv sync --locked --group dev` | Install locked deps (CI uses `--locked --group dev`) |
| `uv run python -m unittest discover -s tests -v` | 35 unit tests |
| `uv run ruff check main.py provider tools tests scripts` | Lint |
| `uv run ruff format --check main.py provider tools tests scripts` | Format check (CI gate) |
| `uv audit --locked` | Dependency audit |
| `uv run --group fuzz python -m tests.fuzz_smart_trim -max_total_time=60` | Fuzz the output contract (Linux only) |
| `dify plugin package . -o dist/text_fitter-<version>.difypkg` | Build marketplace package |
| `python scripts/verify_package.py dist/<pkg>.difypkg HEAD` | Check a built package against the source tree |
| `gh workflow run scorecard.yml --ref main` | Re-run Scorecard (the score and the alerts only refresh on a run) |

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
tests/test_bestpractices_json.py  # keeps the badge self-attestation honest
tests/fuzz_smart_trim.py   # atheris fuzz target for the output contract
scripts/verify_package.py  # compares a built .difypkg with the source tree
.bestpractices.json        # OpenSSF Best Practices self-attestation
docs/architecture.md       # component map + algorithm flow (Mermaid)
```

Invocation: `_invoke` → `_do_invoke` (normalizes `max_chars`/`method`/`mmr_lambda`)
→ `_extract_key_sentences` → `_split_sentences` → `_score_sentences` →
`_greedy_select` | `_mmr_select` → `_yield_outputs` (1 text + 5 variable + 1 JSON
message).

## Workflows

- `ci.yml` — unit tests, Ruff, dependency audit, fuzz job. The `test` job is
  the status check branch protection requires; the `Fuzz` job runs in the same
  workflow but is not a required check.
- `codeql.yml` — CodeQL on push, pull request and a weekly cron.
- `codeql-backfill.yml` — manual; analyses a commit that predates CodeQL.
- `scorecard.yml` — OpenSSF Scorecard; publishes the score and the alerts.
- `release.yml` — on a `v*` tag: builds, verifies, attests, publishes the
  release. It can also be dispatched by hand with a `tag` input; the tag it
  works on comes from `inputs.tag || github.ref_name`, never from
  `GITHUB_REF_NAME` (a manual run is dispatched from a branch, so that would
  name the branch).

## Gotchas

**Packaging.** `.difyignore` alone decides what ships. It must keep `dist/`,
`docs/`, `tests/`, `scripts/`, `.bestpractices.json`, `pyproject.toml`,
`*.difypkg`, `.env.example` and caches out. Anything left in
the repository root that is not listed there lands in the release — a scratch
file, or a stale `.difypkg` — while `dist/` itself is excluded, so build
output never ships. Verify after every build:

```bash
python -c "import zipfile; print(zipfile.ZipFile('dist/<pkg>.difypkg').namelist())"
```

**The package is built from the working tree, not from the git blobs.** A file
with CRLF endings in the working tree ships with CRLF, so the artifact stops
matching the tagged source even though the content is identical. `git status`
does not show it: `.gitattributes` normalises the comparison. `git checkout --
<path>` does not fix it either, because git sees the normalised content as
unchanged — delete the file and check it out again to get the `eol=lf` form.

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

**The badge self-attestation lives in `.bestpractices.json`.** The OpenSSF
Best Practices entry (project 17040, `passing` level) is filled from that
file: the badge app reads it from the repository root and pre-fills the edit
form. It is the reviewable record of the answers behind the badge, so it has
to stay in step with the repository — a justification that points at a file or
a workflow that has since moved would make the attestation wrong.
`tests/test_bestpractices_json.py` checks the file against a snapshot of the
badge app's criteria rules and verifies that every repository path a
justification cites still exists; refresh the snapshot in that test when the
badge app changes its criteria.

Two rules govern how the file is applied. The badge app's automation
confidence for it is 3.5, below the override threshold of 4, so it can only
fill **blank** fields — it never overrides a value that is already set, and
`name` and `description` are filled from GitHub when the project is created.
To change an existing field, use an automation proposal URL instead, with
`overrides=` naming the fields to force:

```text
https://www.bestpractices.dev/en/projects/17040/passing/edit?overrides=name%2Cdescription&name=...&description=...
```

The proposal pre-fills the form; a human still has to save it.

**Branch protection.** `main` requires a pull request, one approving review and
the `test` and `Analyze (python)` status checks — the job names, not the
workflow names (`CI` and `CodeQL`) — with the branch required to be up to date.
`enforce_admins` is off on purpose — the repository has a single maintainer, so
enforcing it would block every merge. Do not "fix" it.

**The `dify` CLI is not a project dependency.** It is a Go binary published with
`langgenius/dify-plugin-daemon` and installed on the machine, so `uv sync` never
provides it; CI downloads it and pins it by version and checksum.

**The fuzz target needs Linux.** Atheris ships no Windows wheel, so exercise
`tests/fuzz_smart_trim.py` locally with a stub `atheris` module on `sys.path`;
the target only uses `atheris.Setup` and `atheris.Fuzz`.

**Adding a directory means touching three places.** A new top-level directory
has to appear in `.difyignore` (so it does not ship), in the ruff commands
(so CI lints it) and in the file map above (so it is findable). Missing the
ruff one leaves the directory unlinted without any error.

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
3. Build the package locally and check it against the source tree:
   ```bash
   dify plugin package . -o dist/text_fitter-<version>.difypkg
   python scripts/verify_package.py dist/text_fitter-<version>.difypkg HEAD
   ```
   The verifier compares every packaged file with the git blob it came from,
   so it catches the two drifts that `.difypignore` cannot: a scratch file in
   the repository root, and a file whose working-tree line endings differ
   from the committed ones.
4. Pre-flight the marketplace validators (needs `yq` on PATH):
   ```bash
   git clone --depth 1 https://github.com/langgenius/dify-marketplace-toolkit
   cd dify-marketplace-toolkit
   python validator/validate-difypkg.py <abs-path-to-pkg> --toolkit-dir . \
     --pr-body-file <pr-body.md> --output-dir <out>
   ```
5. Tag the commit and push the tag. Put a hand-written body in
   `docs/release-notes/v<version>.md` — the file name carries the `v` of the
   tag, e.g. `docs/release-notes/v0.0.3.md` — if you want one; without it the
   workflow generates the notes from the commits. The `Release` workflow builds the package
   from a clean checkout of the tag, verifies it the same way, attests it and
   publishes the GitHub Release with the `.difypkg` asset, its SHA256 and the
   command to verify the attestation:

   ```bash
   gh attestation verify text_fitter-<version>.difypkg \
     --repo AlexMultiAgent/dify-plugin-text-fitter
   ```
   The workflow pins the Dify plugin CLI by version and checksum; it is a Go
   binary published with `langgenius/dify-plugin-daemon`, not a Python package.
6. PR to `langgenius/dify-plugins`: change exactly one `.difypkg` (removing older
   versions in the same directory is allowed), named `<plugin>-<version>.difypkg`.
   The body follows that repo's PR template and must be English-only, with
   `## Plugin information`, `## Submission type`, `## Risk level`,
   `## What changed` and `## Local validation` filled in.
