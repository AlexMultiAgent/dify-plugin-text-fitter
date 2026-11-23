# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability
reporting:

<https://github.com/AlexMultiAgent/dify-plugin-text-fitter/security/advisories/new>

Do not open a public issue for a vulnerability. A public issue is visible to
everybody the moment it is filed and cannot be retracted, which takes the
disclosure timeline out of your hands. The maintainer can also be reached at
the contact address published in `manifest.yaml` (`zhangven@gmail.com`).

## What Counts as a Vulnerability

Text Fitter runs inside the Dify plugin sandbox: no network, no credentials,
Python standard library only. A report is in scope when it shows that crafted
input can break one of the guarantees the plugin makes.

- **Output contract violation** — the returned text exceeds `max_chars`, or the
  internal-error path returns more than the budget allows.
- **Information disclosure** — the plugin leaks a traceback, host file content,
  an environment variable, or any other data the caller never sent.
- **Sandbox escape** — crafted input reaches the host filesystem, the network,
  or another plugin's state.
- **Code execution** — untrusted input ends up in an `eval`, an `exec`, a
  `pickle`, a `yaml.load`, or an import path.
- **Content tampering** — the plugin rewrites, reorders, or injects text the
  caller did not send, breaking the verbatim guarantee.
- **A dependency vulnerability that is exploitable through the plugin runtime.**

Not vulnerabilities: lossy or imperfect trimming, surprising sentence
boundaries, an unexpected `algorithm` value, documentation gaps, and issues in
the Dify platform itself. Those belong in the issue tracker.

## What to Expect

- An acknowledgement of the report within 7 days.
- A triage result — confirmed, not reproducible, or out of scope — within
  30 days.
- A fix released as a new patch version, plus a GitHub Security Advisory when a
  coordinated disclosure is warranted.
- Credit in the advisory, unless you ask to stay anonymous.

We aim to acknowledge a report within 7 days and to publish a fix or an
advisory within 90 days. If a fix needs longer, the disclosure date is agreed
with the reporter instead of being announced on our own. Disclosure happens
after the fix ships or after the advisory is published, never before.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.0.2   | :white_check_mark: |
| < 0.0.2 | :x:                |

Only the latest release of the `0.0.x` series receives fixes. Upgrade to the
latest release before reporting an issue against an older version.
