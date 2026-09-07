#!/usr/bin/env python3
"""Walidacja Conventional Commits 1.0 dla hooka commit-msg (lefthook).

Użycie (wywoływane przez lefthook, nie ręcznie):
    python scripts/check_commit_msg.py <plik-z-trescia-commita>

Zero zależności, działa na Win/Mac/Linux (stąd Python zamiast sh+grep).
Ten sam regex co pierwotny hook i CI (zachowana kompatybilność).
"""

import re
import sys

PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^()]*\))?(!)?: [^ ].*"
)

# Commity generowane przez gita przepuszczamy bez walidacji.
SKIP_PREFIXES = (
    "Merge branch",
    "Merge pull request",
    "Merge remote-tracking branch",
    'Revert "',
)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Użycie: {sys.argv[0]} <plik-commit-msg>", file=sys.stderr)
        return 2

    with open(sys.argv[1], encoding="utf-8") as f:
        subject = f.readline().rstrip("\n")

    if subject.startswith(SKIP_PREFIXES):
        return 0

    if not PATTERN.match(subject):
        print("BŁĄD: commit nie spełnia Conventional Commits.", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Oczekiwano:  <type>[scope][!]: <opis>", file=sys.stderr)
        print("  Np.:         feat(tui): dodaj sortowanie po porcie", file=sys.stderr)
        print(
            "               fix(docker): popraw parsowanie IPv6 w Ports",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print(
            "  Typy: feat fix docs style refactor perf test build ci chore revert",
            file=sys.stderr,
        )
        print(f"  Otrzymano:   {subject}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Szczegóły: docs/conventional-commits.md", file=sys.stderr)
        return 1

    if len(subject) > 100:
        print(
            f"OSTRZEŻENIE: temat ma {len(subject)} znaków (>100). "
            "Rozważ skrócenie.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
