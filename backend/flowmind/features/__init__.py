"""Reusable behavioral feature computation (spec Phase 33, FR-1.12).

Only `node_features.py::compute_node_behavioral_features` is implemented
so far -- a generic, window-agnostic per-node feature computation. Window
orchestration (Phase 34) and fingerprint assembly (Phase 35) are separate,
later phases; see `docs/architecture/behavioral_feature_store.md`.
"""
