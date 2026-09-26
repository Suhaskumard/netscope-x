"""Independent reference values for the Phase 99 browser check.

    python -m scripts.attribution_expected --root <artifact_root> --capture <id> --out expected.json

Recomputes, straight from the pipeline's raw signals and the noisy-OR formula written out again here (not through
`backend.dependency.attribution`), each dependency's strength and the per-signal Shapley contributions as the average marginal
gain over ALL 120 orderings of the five signals. The browser check compares the rendered page with this file.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

from backend.app.core.config import get_settings
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges

ORDER = ["frequency", "persistence", "directionality", "traffic_characteristics", "temporal_precedence"]


def expected(root: Path, capture_id: str) -> list:
    st = get_settings()
    deps = estimate_dependency_strength(root, capture_id)
    edges = discover_edges(root, capture_id, discover_nodes(root, capture_id))
    out = []
    for d, e in zip(deps, edges):
        s = st.dependency_signal_strength
        t = [1 - math.exp(-d.frequency / st.dependency_frequency_scale),
             s * (1 - math.exp(-d.persistence_seconds / st.dependency_persistence_scale)),
             s * d.directionality_score, s * e.confidence, s * d.temporal_precedence_score]
        surv = 1.0
        for x in t:
            surv *= 1 - x
        strength = 1 - surv
        gains = [0.0] * 5
        perms = list(itertools.permutations(range(5)))
        for perm in perms:
            cur = 1.0
            for i in perm:
                nxt = cur * (1 - t[i])
                gains[i] += cur - nxt
                cur = nxt
        out.append({"dependency_id": d.dependency_id, "strength": strength, "stored_strength": d.strength,
                    "raw": [d.frequency, d.persistence_seconds, d.directionality_score, e.confidence, d.temporal_precedence_score],
                    "terms": t, "contribution": [g / len(perms) for g in gains]})
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--capture", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    data = expected(a.root, a.capture)
    a.out.write_text(json.dumps({"order": ORDER, "dependencies": data}))
    print(len(data), "dependencies")
