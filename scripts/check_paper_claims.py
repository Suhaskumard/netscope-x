"""Phase 107: verify every number in the paper draft is backed by a real, quoted measurement.

    python -m scripts.check_paper_claims [--paper docs/research/paper_draft.md] [--ledger docs/research/paper_claims.json]

Each ledger entry {source, quote} must be an exact (whitespace-normalized) quotation from its source document. Every line of the paper
that contains a number must cite ledger entries as [C<n>], and every number on that line must appear in the cited quotes.
Definitional numbers (RQ1, Phase 70, Section 2, headings, citation markers) are exempt. Exit code 1 on any violation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_NUM = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_CITE = re.compile(r"\[(C\d+(?:\s*,\s*C\d+)*)\]")
_EXEMPT = re.compile(r"\bRQ\d(?:\s*[-–]\s*(?:RQ)?\d)?|\bPhases?\s+\d+(?:\s*[-–]\s*\d+)?|\bSection\s+\d+|\bP\d+\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def numbers(text: str) -> set[str]:
    return set(_NUM.findall(text))


def check(paper_text: str, ledger: dict, root: Path) -> list[str]:
    problems: list[str] = []
    sources: dict[str, str] = {}
    for cid, e in ledger.items():
        src = sources.setdefault(e["source"], _norm((root / e["source"]).read_text(encoding="utf-8")))
        if _norm(e["quote"]) not in src:
            problems.append(f"{cid}: quote not found in {e['source']}")
    used: set[str] = set()
    for n, line in enumerate(paper_text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        cited = [c.strip() for m in _CITE.findall(line) for c in m.split(",")]
        used.update(cited)
        body = _EXEMPT.sub(" ", _CITE.sub(" ", line))
        nums = numbers(body)
        if not nums:
            continue
        if not cited:
            problems.append(f"line {n}: numbers {sorted(nums)} with no citation")
            continue
        missing = [c for c in cited if c not in ledger]
        if missing:
            problems.append(f"line {n}: unknown claim(s) {missing}")
            continue
        allowed = set().union(*(numbers(ledger[c]["quote"]) for c in cited))
        bad = sorted(nums - allowed)
        if bad:
            problems.append(f"line {n}: numbers {bad} are not in the cited quotes {cited}")
    for cid in sorted(set(ledger) - used, key=lambda c: int(c[1:])):
        problems.append(f"{cid}: in the ledger but never cited")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--paper", type=Path, default=Path("docs/research/paper_draft.md"))
    ap.add_argument("--ledger", type=Path, default=Path("docs/research/paper_claims.json"))
    a = ap.parse_args()
    ledger = json.loads((a.root / a.ledger).read_text(encoding="utf-8"))
    problems = check((a.root / a.paper).read_text(encoding="utf-8"), ledger, a.root)
    for p in problems:
        print("FAIL:", p)
    print(f"{len(ledger)} claims, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
