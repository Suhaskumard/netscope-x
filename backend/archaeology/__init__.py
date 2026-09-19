"""ARCHAEOLOGY: temporal network intelligence over reconstructed topology
(spec Phases 43-49, "Temporal Intelligence (Network Archaeology)").

Phase 43's `as_of`-aware topology reconstruction
(`backend/nettrace/topology/graph.py`) lives in `nettrace/` since it's a
direct, minimal extension of that package's own Phase 29-32 functions.
This package holds the first code with no natural home there: versioned
snapshot generation (`snapshots.py`, Phase 44) and, in later phases,
structural diffing, behavioral evolution tracking, timelines, change
attribution, and historical investigation queries.

Like every other pipeline module, imports shared schemas from
`backend.app.models` (Phase 04) but never imports `simulator.ground_truth`
directly -- enforced structurally by `scripts/check_ground_truth_boundary.py`
(Phase 17).
"""
