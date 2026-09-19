"""Causal candidate generation (spec Phase 53, FR-1.27 second half: "generate
candidate causal relationships. Do not equate correlation with causation").

The design boundary was already committed back at Phase 05:
`docs/architecture/algorithm_selection.md` section 6 evaluated and rejected
constraint-based causal discovery (e.g. the PC algorithm) over the full
node-activity dataset, stating outright that "the spec's own Phase 53
wording ... is satisfied by a scored-candidate approach without requiring
full causal-graph discovery." So this module is not a new causal-inference
algorithm -- it is a filter/promotion step over Phase 51/52's already-real
`DependencyEdge` list, producing an explicitly-labeled *candidate* set,
never a confirmed claim.

The qualifying rule is the literal, structural implementation of "do not
equate correlation with causation": a `DependencyEdge` is promoted only
when it has BOTH sufficient `strength` (built from frequency, persistence,
directionality, and traffic characteristics -- fundamentally
correlation/communication evidence) AND a real, positive
`temporal_precedence_score` (Phase 52 -- the one signal that specifically
supports directional, time-ordered evidence, the logical prerequisite for
a causal claim, not proof of one). `strength` alone, however high, is
deliberately never sufficient by itself.

`GET /causal/{dependency_id}` (`backend/app/api/routes/causal.py`) stays
untouched -- its own docstring already scopes it to "spec Phase 56 (Causal
Evidence Report)", a later phase this module does not attempt. No new
Pydantic schema either, following the precedent already set by Phase 32's
`TopologyComparisonResult`, Phase 37's `RoleCalibrationEvaluation`, Phase
42's `AnomalyDetectionEvaluation`, and Phase 46's `BehavioralEvolutionEvent`
(all downstream, filtering/evaluation-style concepts with no Phase 04
schema reserved for them).

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.app.models.dependency import DependencyEdge

_DEFAULT_STRENGTH_THRESHOLD = 0.5  # mirrors Settings.causal_candidate_strength_threshold's own default

CAUSAL_CANDIDATE_DISCLAIMER = (
    "This is a candidate for further investigation only -- strength and temporal precedence "
    "are correlational and temporal-ordering evidence, not proof of causation. A full causal "
    "evidence report (spec Phase 56) is required before this can be treated as more than a lead."
)


@dataclass(frozen=True)
class CausalCandidate:
    dependency_id: str
    source_node_id: str
    target_node_id: str
    strength: float
    temporal_precedence_score: float
    rationale: List[str]


def generate_causal_candidates(
    dependencies: List[DependencyEdge],
    strength_threshold: float = _DEFAULT_STRENGTH_THRESHOLD,
) -> List[CausalCandidate]:
    """Promotes each `DependencyEdge` meeting both qualifying conditions
    (`strength >= strength_threshold` AND `temporal_precedence_score >
    0.0`) to a `CausalCandidate`. Returns `[]` for empty `dependencies`,
    never an error. Deterministically ordered by `strength` descending,
    tie-broken by `dependency_id`.
    """
    candidates: List[CausalCandidate] = []
    for dependency in dependencies:
        if dependency.strength < strength_threshold:
            continue
        if dependency.temporal_precedence_score <= 0.0:
            continue

        rationale = [
            f"strength {dependency.strength:.3f} meets threshold {strength_threshold:.3f}",
            f"temporal_precedence_score {dependency.temporal_precedence_score:.3f} indicates "
            f"{dependency.source_node_id} consistently precedes {dependency.target_node_id}",
        ]
        candidates.append(
            CausalCandidate(
                dependency_id=dependency.dependency_id,
                source_node_id=dependency.source_node_id,
                target_node_id=dependency.target_node_id,
                strength=dependency.strength,
                temporal_precedence_score=dependency.temporal_precedence_score,
                rationale=rationale,
            )
        )

    return sorted(candidates, key=lambda c: (-c.strength, c.dependency_id))


def format_causal_candidate(candidate: CausalCandidate) -> str:
    """Renders one `CausalCandidate` as a human-readable report, always
    ending with `CAUSAL_CANDIDATE_DISCLAIMER` -- structural, not
    confidence-gated, mirroring Phase 48's `format_change_attribution`
    (`backend/archaeology/attribution.py`) unconditional-disclaimer
    pattern extended to this new artifact type."""
    lines = [
        f"Candidate: {candidate.source_node_id} -> {candidate.target_node_id}",
        f"Dependency: {candidate.dependency_id}",
        f"Strength: {candidate.strength:.3f}",
        f"Temporal precedence: {candidate.temporal_precedence_score:.3f}",
        "Rationale:",
    ]
    lines.extend(f"- {reason}" for reason in candidate.rationale)
    lines.append(CAUSAL_CANDIDATE_DISCLAIMER)
    return "\n".join(lines)
