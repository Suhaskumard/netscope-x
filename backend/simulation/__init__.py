"""SIMULATION: controlled failure injection, dynamic path analysis, and
failure propagation over a digital twin's topology (spec Phases 59-61,
"Failure Injection Framework, Dynamic Path Engine, Failure Propagation
Simulator").

Phase 59 (`failure_injection.py`) applies a `FailureScenario`
(`backend.app.models.failure`, Phase 04) to a `TopologyGraph`, producing
an isolated, possibly-modified copy. Phase 60 (`path_engine.py`) provides
path-cost computation: shortest paths, alternate paths (Yen's algorithm),
route-change comparison, and connectivity analysis over a (possibly
failure-modified) `TopologyGraph`, deriving edge weight from confidence
and Phase 59's `degraded_edge_ids`/`FailureScenario` magnitude fields.
Phase 61 (`failure_propagation_pipeline.py`, `run_failure_propagation_
pipeline`/`FailurePipelineResult`/`ServiceImpact`) composes both of those
with Phase 54's `propagate_failure`
(`backend.dependency.failure_propagation`) into one connected
failure -> dependency propagation -> routing impact -> service impact
pipeline, reimplementing none of the three's own logic -- pure
orchestration, per FR-1.34.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""
