"""Human-readable anomaly explanations (spec Phase 41, FR-1.18).

FR-1.18: "Every reported anomaly shall include concrete supporting
evidence... never a bare label." Phase 40's detector already produces that
evidence as real `Anomaly.evidence`/`evidence_values` content (see
`backend/flowmind/anomaly/node_anomaly.py`) -- this module doesn't compute
any new evidence. Its one job is presentation: turning one or more
already-detected `Anomaly` objects for the same node into the plain,
multi-line report shape the master spec's own Phase 41 worked example
illustrates:

    Node: API-2
    New destination: X
    Historical destinations: 4
    Current destinations: 9
    New port: 4444
    Evidence: ...

`format_anomaly_report` builds this generically from each `Anomaly`'s own
`evidence_values` dict (turning `historical_destinations` into
"Historical destinations", in whatever order the detector already put
them in) plus its `evidence` sentences -- it doesn't hardcode per-dimension
field names, so it renders any current or future `AnomalyDimension`
unchanged.

Deliberately a pure, side-effect-free function over caller-supplied
`Anomaly` objects: no persistence, no API wiring. `GET /anomalies`
(`backend/app/api/routes/anomalies.py`) stays a 501 stub -- there is still
no anomaly persistence layer to source real records from, and wiring an API
response-formatting choice is separate work from producing the format
itself. See `docs/architecture/explainable_anomalies.md` for the full
design and worked example.

Never imports `simulator.ground_truth` (spec §4) -- trivially true, this
module only ever touches already-constructed `Anomaly` objects.
"""

from __future__ import annotations

from typing import List

from backend.app.models.anomaly import Anomaly


def _field_label(key: str) -> str:
    words = key.replace("_", " ")
    return words[0].upper() + words[1:] if words else words


def format_anomaly_report(anomalies: List[Anomaly]) -> str:
    """Renders `anomalies` (all belonging to one node) into a single
    human-readable, multi-line explanation: a `Node: <id>` header, one
    `<Label>: <value>` line per key in every anomaly's `evidence_values`
    (in the order the detector produced them), then an `Evidence:` section
    listing every anomaly's own `evidence` sentence(s).

    Raises `ValueError` if `anomalies` is empty or spans more than one
    `node_id` -- a report is inherently node-scoped, mirroring this
    project's established fail-fast convention for mismatched inputs
    (e.g. `node_anomaly._check_fingerprint_matches_baseline`,
    `node_baseline.build_node_baseline`'s node/window checks).
    """
    if not anomalies:
        raise ValueError("format_anomaly_report requires at least one anomaly")

    node_ids = {a.node_id for a in anomalies}
    if len(node_ids) > 1:
        raise ValueError(f"anomalies must all share one node_id, got {node_ids}")

    lines = [f"Node: {anomalies[0].node_id}"]

    for anomaly in anomalies:
        for key, value in anomaly.evidence_values.items():
            lines.append(f"{_field_label(key)}: {value}")

    lines.append("Evidence:")
    for anomaly in anomalies:
        for sentence in anomaly.evidence:
            lines.append(f"- {sentence}")

    return "\n".join(lines)
