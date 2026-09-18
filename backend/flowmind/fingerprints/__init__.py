"""Node behavioral fingerprint assembly (spec Phase 35, FR-1.13).

Assembles Phase 33-34's window-scoped `NodeBehavioralFeatures` into real,
persistable `BehavioralFingerprint` instances. Role inference (Phase
36-37) and `GET /behaviors/{node_id}` API wiring are separate, later
work -- see `docs/architecture/node_behavioral_fingerprints.md`.
"""
