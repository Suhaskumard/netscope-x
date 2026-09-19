"""Causal Evidence Report (spec Phase 56, FR-1.30: "for every inferred
dependency or propagation relationship provide: relationship, evidence,
confidence, counter-evidence, limitations").

`backend/app/models/dependency.py`'s `CausalEvidenceReport` (Phase 04) has
never been constructed anywhere until this phase. Two relationship kinds,
per FR-1.30's own "dependency OR propagation" wording: Phase 50-53's
`DependencyEdge`/`CausalCandidate`, and Phase 54's `PropagationImpact`.
Both builders are pure functions over caller-supplied, already-computed
data, mirroring Phase 41/42/45/53/54's own precedent -- reusing every
upstream signal already computed rather than re-deriving anything.

`CONFOUNDER_LIMITATION`/`THRESHOLD_LIMITATION` are always present in
`limitations` (schema-required non-empty) -- structural properties of the
scoring approach itself, true regardless of any specific edge's numbers.
`counter_evidence` is the opposite: genuine, per-edge signals only, never
manufactured filler to avoid looking empty (the schema doesn't require it
non-empty, unlike `evidence`/`limitations`) -- a strong, fully-evidenced
candidate can legitimately have none.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from backend.app.models.dependency import CausalEvidenceReport, DependencyEdge
from backend.app.models.failure import ImpactOrder, PropagationImpact
from backend.dependency.causal_candidates import CausalCandidate

_DIRECTIONALITY_COUNTER_THRESHOLD = 0.3  # below this, traffic is "largely bidirectional"

CONFOUNDER_LIMITATION = (
    "This score is a correlational, multi-signal heuristic (frequency, persistence, "
    "directionality, temporal precedence, traffic characteristics), not a randomized "
    "controlled experiment -- causation is not proven, only made more or less plausible. A "
    "high-frequency, persistent, one-directional but coincidental communication pattern (e.g. a "
    "health-check poller) can still score deceptively high (algorithm_selection.md section 6)."
)

THRESHOLD_LIMITATION = (
    "Strength/temporal-precedence thresholds used to decide causal-candidate status are "
    "provisional, uncalibrated constants pending Phase 68 evaluation against ground truth."
)

PROPAGATION_LIMITATION = (
    "Multi-hop propagation compounds each hop's own uncertainty and has not itself been "
    "validated against a real controlled failure experiment -- that validation is Phase 63/68's "
    "job, not performed here."
)


def _dependency_relationship(dependency: DependencyEdge, is_candidate: bool) -> str:
    if is_candidate:
        return (
            f"{dependency.source_node_id} is a causal candidate for "
            f"{dependency.target_node_id} (not a confirmed cause)"
        )
    return (
        f"{dependency.source_node_id} and {dependency.target_node_id} communicate "
        f"(estimated dependency strength {dependency.strength:.3f}); no causal direction is "
        "established"
    )


def _dependency_evidence(dependency: DependencyEdge) -> List[str]:
    return [
        f"frequency {dependency.frequency:.3f} events/sec",
        f"persistence {dependency.persistence_seconds:.1f}s",
        f"directionality_score {dependency.directionality_score:.3f}",
        f"temporal_precedence_score {dependency.temporal_precedence_score:.3f}",
    ]


def _dependency_counter_evidence(dependency: DependencyEdge, is_candidate: bool) -> List[str]:
    counter: List[str] = []
    if dependency.temporal_precedence_score <= 0.0:
        counter.append(
            "no positive temporal-precedence evidence supports a causal direction between "
            "these nodes -- could be purely coincidental co-occurrence"
        )
    if dependency.directionality_score < _DIRECTIONALITY_COUNTER_THRESHOLD:
        counter.append(
            f"traffic is largely bidirectional (directionality_score="
            f"{dependency.directionality_score:.3f}), also consistent with two independent "
            "peers rather than a clear dependency direction"
        )
    if not is_candidate:
        counter.append("strength does not meet the causal-candidate threshold (spec Phase 53)")
    return counter


def build_dependency_evidence_report(
    dependency: DependencyEdge,
    candidate: Optional[CausalCandidate] = None,
    generated_at: Optional[datetime] = None,
) -> CausalEvidenceReport:
    """Builds a `CausalEvidenceReport` for a dependency relationship.
    `candidate` should be the matching `CausalCandidate` (Phase 53) for
    this `dependency`, if it qualified, or `None` if it didn't --
    determines whether `relationship`/`counter_evidence` use the stronger
    "causal candidate" wording or the weaker "mere communication" wording.
    """
    is_candidate = candidate is not None
    return CausalEvidenceReport(
        report_id=f"{dependency.dependency_id}:causal_evidence",
        relationship=_dependency_relationship(dependency, is_candidate),
        evidence=_dependency_evidence(dependency),
        confidence=dependency.strength,
        counter_evidence=_dependency_counter_evidence(dependency, is_candidate),
        limitations=[CONFOUNDER_LIMITATION, THRESHOLD_LIMITATION],
        generated_at=generated_at or datetime.now(timezone.utc),
    )


def build_propagation_evidence_report(
    impact: PropagationImpact,
    candidates: List[CausalCandidate],
    generated_at: Optional[datetime] = None,
) -> CausalEvidenceReport:
    """Builds a `CausalEvidenceReport` for a `SECONDARY`/`TERTIARY`
    propagation impact. `candidates` must be the same list
    `propagate_failure` was called with, so the specific `CausalCandidate`
    that caused this hop can be found and its `strength` reused as
    `confidence`.

    Raises `ValueError` for a `PRIMARY` impact -- the given failure, not
    an inferred relationship, so there is nothing to report evidence for
    -- or if no matching candidate is found (an internally inconsistent
    call).
    """
    if impact.order == ImpactOrder.PRIMARY:
        raise ValueError(
            "a PRIMARY impact is the given failure, not an inferred relationship -- no report "
            "to generate"
        )

    candidate = next(
        (
            c
            for c in candidates
            if c.source_node_id == impact.caused_by_node_id and c.target_node_id == impact.affected_node_id
        ),
        None,
    )
    if candidate is None:
        raise ValueError(
            f"no CausalCandidate found for {impact.caused_by_node_id} -> "
            f"{impact.affected_node_id}; candidates must be the same list propagate_failure "
            "was called with"
        )

    return CausalEvidenceReport(
        report_id=f"{impact.scenario_id}:{impact.affected_node_id}:causal_evidence",
        relationship=(
            f"failure of {impact.caused_by_node_id} is estimated to propagate to "
            f"{impact.affected_node_id} ({impact.order.value} impact)"
        ),
        evidence=list(impact.evidence),
        confidence=candidate.strength,
        counter_evidence=[],
        limitations=[CONFOUNDER_LIMITATION, THRESHOLD_LIMITATION, PROPAGATION_LIMITATION],
        generated_at=generated_at or datetime.now(timezone.utc),
    )
