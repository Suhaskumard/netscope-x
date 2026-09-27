"""Phase 107: the paper-claims checker rejects unbacked/mismatched numbers and accepts the real draft."""
import json
from pathlib import Path

from scripts.check_paper_claims import check, numbers

ROOT = Path(__file__).resolve().parents[2]


def _setup(tmp_path: Path, quote: str = "F1 was 0.912 in 10 seeds"):
    (tmp_path / "src.md").write_text("Result:\n  F1 was 0.912   in 10 seeds, done.\n", encoding="utf-8")
    return {"C1": {"source": "src.md", "quote": quote}}


def test_backed_number_passes_and_definitional_numbers_are_exempt(tmp_path):
    ledger = _setup(tmp_path)
    assert check("## RQ1 heading 5\nIn Phase 70 (RQ2) F1 was 0.912 [C1].\n", ledger, tmp_path) == []


def test_unbacked_number_and_missing_citation_are_flagged(tmp_path):
    ledger = _setup(tmp_path)
    assert any("not in the cited quotes" in p for p in check("F1 was 0.913 [C1].\nC1 [C1]", ledger, tmp_path))
    assert any("no citation" in p for p in check("F1 was 0.912.\nsee [C1]", ledger, tmp_path))


def test_fabricated_quote_and_unused_claim_are_flagged(tmp_path):
    bad = _setup(tmp_path, quote="F1 was 0.999 in 10 seeds")
    assert any("quote not found" in p for p in check("text [C1]", bad, tmp_path))
    assert any("never cited" in p for p in check("no claims here", _setup(tmp_path), tmp_path))


def test_number_tokenizer():
    assert numbers("0.75-1.0 and 11,530 pkts, p50, 96/96") == {"0.75", "1.0", "11,530", "96"}


def test_real_paper_is_fully_backed():
    ledger = json.loads((ROOT / "docs/research/paper_claims.json").read_text(encoding="utf-8"))
    assert check((ROOT / "docs/research/paper_draft.md").read_text(encoding="utf-8"), ledger, ROOT) == []
