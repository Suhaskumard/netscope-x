"""DIGITAL TWIN: a computational model combining topology, behavior,
history, dependencies, routing, and state (spec Phases 57-58, "Digital
Twin, Simulation, and Counterfactuals").

This is the first code in a new spec section. Phase 57 (`twin.py`) builds
the static assembly, reusing every already-real artifact from earlier
phases (Phase 32's TopologyGraph, Phase 35's BehavioralFingerprint, Phase
44/47's NetworkSnapshot/GraphChangeEvent, Phase 51-53's DependencyEdge) --
no new inference. Synchronization from new observations (Phase 58),
failure injection (Phase 59), the dynamic path engine (Phase 60), and
counterfactuals (Phase 64-66) are later phases' additions here.

Like every other pipeline module, imports shared schemas from
`backend.app.models` (Phase 04) but never imports `simulator.ground_truth`
directly -- enforced structurally by `scripts/check_ground_truth_boundary.py`
(Phase 17).
"""
