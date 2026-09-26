"""Phase 104: the significance statistics are checked against independent computation, then one small real ablation run end to end."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

import experiments.significance as sig


def _hand_t(d):
    n, mean = len(d), sum(d) / len(d)
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    return mean / (sd / math.sqrt(n)), sd


def test_t_and_p_match_hand_formula_and_scipy():
    d = list(np.random.default_rng(1).normal(0.3, 1.0, 25))
    r = sig.paired_test(d)
    t, sd = _hand_t(d)
    assert r["t"] == pytest.approx(t, rel=1e-12) and r["sd"] == pytest.approx(sd, rel=1e-12) and r["cohens_dz"] == pytest.approx(sum(d) / len(d) / sd)
    ref = stats.ttest_rel(np.asarray(d), np.zeros(len(d)))
    assert r["p"] == pytest.approx(ref.pvalue, rel=1e-9)


def test_bootstrap_ci_is_deterministic_and_covers_known_mean():
    d = list(np.random.default_rng(2).normal(0.5, 1.0, 200))
    a, b = sig.paired_test(d, rng_seed=7), sig.paired_test(d, rng_seed=7)
    assert a["ci95"] == b["ci95"]
    assert a["ci95"][0] < 0.5 < a["ci95"][1] and a["ci95"][0] < float(np.mean(d)) < a["ci95"][1]
    assert sig.paired_test(d, rng_seed=8)["ci95"] != a["ci95"]


def test_holm_known_vector():
    assert sig.holm_adjust([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert sig.holm_adjust([0.5, 0.9]) == pytest.approx([1.0, 1.0])
    assert sig.holm_adjust([]) == []


def test_min_detectable_difference_known_case():
    d = [1.0, -1.0] * 5  # n = 10, sd = sqrt(10/9)
    r = sig.paired_test(d)
    expected = (stats.t.ppf(0.975, 9) + stats.t.ppf(0.8, 9)) * r["sd"] / math.sqrt(10)
    assert r["min_detectable_diff_80pct_power"] == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(0.99472 * r["sd"], rel=1e-3)


def test_degenerate_small_and_constant_shift():
    assert sig.paired_test([0.0] * 6)["verdict_raw"] == "identical"
    assert sig.paired_test([0.1, 0.2])["verdict_raw"] == "insufficient_n"
    c = sig.paired_test([0.25] * 5)
    assert c["verdict_raw"] == "tested" and c["p"] == 0.0 and c["ci95"] == [0.25, 0.25]


def _verdict(d):
    rows = [sig.paired_test(d, 0)]
    sig._apply_family(rows)
    return rows[0]["verdict"]


def test_planted_effect_significant_and_pure_noise_not():
    rng = np.random.default_rng(11)
    assert _verdict(list(rng.normal(0.6, 1.0, 40))) == "significant"
    assert _verdict(list(np.random.default_rng(12).normal(0.0, 1.0, 40))) == "indistinguishable_from_noise"


def _values(deltas, none_at=None):
    v = {}
    for i, delta in enumerate(deltas):
        seed = 100 + i
        v[("small", seed, None)] = {("ctx", "f1"): 0.5 + 0.01 * i}
        v[("small", seed, "without_temporal")] = {("ctx", "f1"): None if i == none_at else 0.5 + 0.01 * i + delta}
    return v


def test_none_pairs_dropped_and_counted_and_cross_check():
    rep = sig.analyze(_values([0.1, 0.12, 0.09, 0.11, 0.1], none_at=2), n_bootstrap=200)
    row = next(r for r in rep["per_topology"] if r["ablation"] == "without_temporal")
    assert row["n"] == 4 and row["pairs_dropped_for_none"] == 1
    assert row["mean_diff"] == pytest.approx((0.1 + 0.12 + 0.11 + 0.1) / 4)
    assert rep["mean_diff_cross_check_max_abs_error"] < 1e-12
    assert next(r for r in rep["pooled"])["n"] == 4


def test_real_small_run_end_to_end(tmp_path):
    rep = sig.run_significance(tmp_path, n_seeds=3, topologies=["small"], rng_seed=0)
    assert (tmp_path / "significance" / "report.md").is_file() and rep["n_seeds"] == 3
    assert rep["mean_diff_cross_check_max_abs_error"] < 1e-12
    pooled = {(r["ablation"], r["context"], r["field"]): r for r in rep["pooled"]}
    # nothing here may be reported significant with n=3 unless the data is a constant shift; whatever is reported must be internally consistent
    for r in pooled.values():
        assert r["verdict"] in ("significant", "inconclusive", "indistinguishable_from_noise", "identical", "insufficient_n")
        if r["verdict"] == "identical":
            assert r["mean_diff"] == 0.0
        if r["verdict"] == "significant":
            assert r["p_holm"] < 0.05 and (r["ci95"][0] > 0 or r["ci95"][1] < 0)
    md = (tmp_path / "significance" / "report.md").read_text(encoding="utf-8")
    assert "Holm" in md and "fixed designs" in md
