"""DEPENDENCY: dependency and causal reasoning over inferred topology (spec
Phases 50-56, "Dependency and Causal Reasoning").

FR-1.25 (Phase 50, RQ5) draws the central design point this package builds
on: "A communicates with B" and "A depends on B" are two structurally
separate types (`CommunicationRelationship`/`DependencyEdge`,
`backend/app/models/dependency.py`, Phase 04) with no implicit cast between
them. This package holds the real computation behind the "communicates"
side first (`communication.py`, Phase 50); dependency-strength estimation,
temporal precedence, failure-propagation, criticality metrics, and causal
evidence reporting are later phases' additions here.

Like every other pipeline module, imports shared schemas from
`backend.app.models` (Phase 04) but never imports `simulator.ground_truth`
directly -- enforced structurally by `scripts/check_ground_truth_boundary.py`
(Phase 17).
"""
