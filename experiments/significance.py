"""Formal significance testing of the Phase 68/72 ablation effects (spec addendum Phase 104).

For each topology level and seed, the baseline cell and each ablation cell (completeness 1.0) are run for real with the SAME seed, so
they share generated packets and differ only by the ablation. Per (ablation, context, field), d = ablated - baseline is tested:

* paired t-test (`scipy.stats.ttest_rel` result reproduced by hand in the tests), two-sided, with Cohen's dz;
* percentile bootstrap 95% CI of mean(d) (seeded, deterministic);
* the minimum mean difference detectable at 80% power for the n actually run, so "not significant" reads as "cannot distinguish
  effects below X", not "no effect";
* Holm-Bonferroni across each family of tests. "significant" needs adjusted p < 0.05 AND a bootstrap CI excluding 0; disagreement
  is "inconclusive".

Groups whose differences are all exactly 0 are `identical` (the t-test is undefined; that is a stronger statement than p = 1).
None metric values drop that pair (never coerced to 0) and n reports what remained. Two scopes: per topology (n = seeds) and pooled
over topology x seed pairs; pooled pairs are not independent draws of "networks" (six fixed designs), and the report says so.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

from experiments.matrix_runner import ABLATIONS, TOPOLOGY_LEVELS, run_matrix_cell
from experiments.multi_seed import METRIC_FIELDS

ALPHA = 0.05
POWER = 0.80
N_BOOTSTRAP = 10_000
MIN_PAIRS = 3
Key = Tuple[str, str]  # (context, field)


def paired_test(d: Sequence[float], rng_seed: int = 0, n_bootstrap: int = N_BOOTSTRAP) -> Dict[str, Any]:
    x = np.asarray(d, dtype=float)
    n = int(x.size)
    out: Dict[str, Any] = {"n": n, "mean_diff": float(x.mean()) if n else None}
    if n < MIN_PAIRS:
        return {**out, "verdict_raw": "insufficient_n"}
    if not np.any(x != 0.0):
        return {**out, "verdict_raw": "identical", "sd": 0.0}
    mean, sd = float(x.mean()), float(x.std(ddof=1))
    if sd == 0.0:  # constant nonzero shift: every pair moved by exactly the same amount
        t, p, dz = math.inf, 0.0, math.inf
    else:
        t = mean / (sd / math.sqrt(n))
        p = float(2 * stats.t.sf(abs(t), n - 1))
        dz = mean / sd
    idx = np.random.default_rng(rng_seed).integers(0, n, size=(n_bootstrap, n))
    lo, hi = np.percentile(x[idx].mean(axis=1), [2.5, 97.5])
    mde = (stats.t.ppf(1 - ALPHA / 2, n - 1) + stats.t.ppf(POWER, n - 1)) * sd / math.sqrt(n)
    return {**out, "sd": sd, "t": t, "p": p, "cohens_dz": dz, "ci95": [float(lo), float(hi)],
            "min_detectable_diff_80pct_power": float(mde), "verdict_raw": "tested"}


def holm_adjust(pvalues: Sequence[float]) -> List[float]:
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def _apply_family(rows: List[Dict[str, Any]]) -> None:
    """Holm across the family's tested rows, then the verdict. Mutates rows."""
    tested = [r for r in rows if r["verdict_raw"] == "tested"]
    for r, adj in zip(tested, holm_adjust([r["p"] for r in tested])):
        r["p_holm"] = adj
        excludes = r["ci95"][0] > 0 or r["ci95"][1] < 0
        if adj < ALPHA and excludes:
            r["verdict"] = "significant"
        elif adj < ALPHA or excludes:
            r["verdict"] = "inconclusive"
        else:
            r["verdict"] = "indistinguishable_from_noise"
    for r in rows:
        r.setdefault("verdict", r["verdict_raw"])
        del r["verdict_raw"]


def collect(root: Path, topologies: Sequence[str], seeds: Sequence[int]) -> Dict[Tuple[str, int, Optional[str]], Dict[Key, Optional[float]]]:
    """Real per-seed values for the baseline and every ablation at completeness 1.0."""
    values: Dict[Tuple[str, int, Optional[str]], Dict[Key, Optional[float]]] = {}
    for topo in topologies:
        for seed in seeds:
            for ablation in (None, *ABLATIONS):
                cell = run_matrix_cell(root, topo, 1.0, seed=seed, ablation=ablation)
                values[(topo, seed, ablation)] = {(m.context.value, f): getattr(m, f) for m in cell.metrics for f in METRIC_FIELDS}
    return values


def analyze(values: Dict[Tuple[str, int, Optional[str]], Dict[Key, Optional[float]]], rng_seed: int = 0,
            n_bootstrap: int = N_BOOTSTRAP) -> Dict[str, Any]:
    topologies = sorted({k[0] for k in values})
    seeds = sorted({k[1] for k in values})
    keys = sorted({k for v in values.values() for k in v})
    per_topology: List[Dict[str, Any]] = []
    pooled: List[Dict[str, Any]] = []
    max_check_err = 0.0
    for ablation in ABLATIONS:
        for key in keys:
            pooled_d: List[float] = []
            pooled_base: List[float] = []
            pooled_abl: List[float] = []
            for topo in topologies:
                d: List[float] = []
                dropped = 0
                for seed in seeds:
                    b = values.get((topo, seed, None), {}).get(key)
                    a = values.get((topo, seed, ablation), {}).get(key)
                    if a is None or b is None:
                        dropped += 1
                        continue
                    d.append(a - b)
                    pooled_base.append(b)
                    pooled_abl.append(a)
                pooled_d += d
                if d or dropped < len(seeds):
                    per_topology.append({"ablation": ablation, "context": key[0], "field": key[1], "topology": topo,
                                         "pairs_dropped_for_none": dropped, **paired_test(d, rng_seed, n_bootstrap)})
            if pooled_d:
                res = paired_test(pooled_d, rng_seed, n_bootstrap)
                # independent cross-check: mean of differences must equal difference of means over the same pairs
                max_check_err = max(max_check_err, abs(res["mean_diff"] - (float(np.mean(pooled_abl)) - float(np.mean(pooled_base)))))
                pooled.append({"ablation": ablation, "context": key[0], "field": key[1], "topology": "ALL", **res})
    _apply_family(per_topology)
    _apply_family(pooled)
    return {"topologies": topologies, "seeds": seeds, "n_seeds": len(seeds), "alpha": ALPHA, "power": POWER, "bootstrap_resamples": n_bootstrap,
            "per_topology": per_topology, "pooled": pooled, "mean_diff_cross_check_max_abs_error": max_check_err}


def _fmt(r: Dict[str, Any]) -> str:
    base = f"{r['ablation']} / {r['context']}.{r['field']} [{r['topology']}] n={r['n']}"
    if r["verdict"] in ("identical", "insufficient_n"):
        return f"{base}: {r['verdict']}"
    lo, hi = r["ci95"]
    return (f"{base}: mean diff {r['mean_diff']:+.4f}, 95% CI [{lo:+.4f}, {hi:+.4f}], p={r['p']:.3g}, Holm p={r['p_holm']:.3g}, "
            f"dz={r['cohens_dz']:.2f}, cannot detect |diff| below {r['min_detectable_diff_80pct_power']:.4f}")


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Ablation significance (Phase 104)", "",
             f"Paired by (topology, seed): baseline vs ablation at completeness 1.0 with identical generated packets. "
             f"Topologies {report['topologies']}, {report['n_seeds']} seeds {report['seeds'][0]}..{report['seeds'][-1]}. "
             f"Two-sided paired t-test, 10,000-resample bootstrap CI, Holm within each family; alpha {report['alpha']}. "
             "Pooled rows treat topology x seed pairs as units, but the six topologies are fixed designs, not a sample of networks.", ""]
    for scope, rows in (("Pooled", report["pooled"]), ("Per topology", report["per_topology"])):
        for verdict, title in (("significant", "Significant"), ("inconclusive", "Inconclusive (p and CI disagree)"),
                               ("indistinguishable_from_noise", "Not distinguishable from noise at this n"),
                               ("identical", "Identical (no effect on any pair)"), ("insufficient_n", "Insufficient n")):
            chosen = [r for r in rows if r["verdict"] == verdict]
            lines += [f"## {scope}: {title} ({len(chosen)})", ""] + [f"- {_fmt(r)}" for r in chosen] + [""]
    return "\n".join(lines)


def run_significance(root: Path, n_seeds: int = 10, seed_start: int = 42, topologies: Optional[Sequence[str]] = None,
                     rng_seed: int = 0) -> Dict[str, Any]:
    topos = list(topologies) if topologies else list(TOPOLOGY_LEVELS)
    seeds = list(range(seed_start, seed_start + n_seeds))
    report = analyze(collect(root, topos, seeds), rng_seed)
    out = root / "significance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
