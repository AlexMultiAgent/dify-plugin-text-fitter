"""Verify that a built .difypkg matches the source tree it was built from.

The package is built from the working tree, not from the git blobs, so it
can drift from the committed source in two ways that no other check catches:
a file with CRLF endings in the working tree ships with CRLF, and a scratch
file left in the repository root ships as well. This script compares the
package against a git ref, file by file, and fails on any difference.

Usage:
    python scripts/verify_package.py dist/text_fitter-0.0.3.difypkg v0.0.3
"""

import fnmatch
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def difyignore_patterns() -> list[str]:
    """Read the packaging filter; it alone decides what ships."""
    text = (REPO_ROOT / ".difyignore").read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def is_excluded(path: str, patterns: list[str]) -> bool:
    """Match a path against the .difyignore patterns."""
    for pattern in patterns:
        if pattern.endswith("/"):
            prefix = pattern[:-1]
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(
            Path(path).name, pattern
        ):
            return True
    return False


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], capture_output=True, check=True, cwd=REPO_ROOT
    ).stdout


def tracked_files(ref: str) -> set[str]:
    output = git("ls-tree", "-r", "--name-only", ref).decode("utf-8")
    return {line for line in output.splitlines() if line}


def blob(ref: str, path: str) -> bytes:
    return git("show", f"{ref}:{path}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    package = Path(sys.argv[1])
    ref = sys.argv[2]

    if not package.is_file():
        print(f"package not found: {package}")
        return 1

    patterns = difyignore_patterns()
    expected = {p for p in tracked_files(ref) if not is_excluded(p, patterns)}

    with zipfile.ZipFile(package) as archive:
        names = {n for n in archive.namelist() if not n.endswith("/")}
        contents = {n: archive.read(n) for n in names}

    problems: list[str] = []
    for extra in sorted(names - expected):
        problems.append(f"not in {ref} or excluded by .difyignore: {extra}")
    for missing in sorted(expected - names):
        problems.append(f"missing from the package: {missing}")
    for name in sorted(names & expected):
        if contents[name] != blob(ref, name):
            problems.append(f"content differs from {ref}: {name}")

    print(f"package : {package}")
    print(f"ref     : {ref}")
    print(f"files   : {len(names)}")
    print(f"sha256  : {sha256_of(package)}")

    if problems:
        print(f"\nFAILED with {len(problems)} difference(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nOK: every packaged file matches the source tree byte for byte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
