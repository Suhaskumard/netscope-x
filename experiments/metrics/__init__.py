"""Evaluation-only metric computation over research artifacts (spec Phase 32+).

Reads and compares already-produced artifacts (inferred topology, ground
truth); never imported by, or imports into, inference code under
`backend/nettrace/`/`backend/app/` -- see `scripts/check_ground_truth_boundary.py`
and `docs/architecture/topology_reconstruction.md`'s ground-truth-boundary
compliance argument.
"""
