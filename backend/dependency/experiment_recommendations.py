"""Experiment Recommendation Engine (spec Phase 67, FR-1.39: "generate
experiment recommendations from measurable structural evidence (e.g.,
high-criticality node -> suggest removal experiment, with stated
reasoning)").

No research question governs this phase (RQ1-RQ7 is the full list; none
names Phase 67). Only one Phase 55 criticality signal was ever explicitly
earmarked for it: `criticality.py`'s own `METRIC_RATIONALE["is_articulation_
point"]` already says it "directly feeds failure-injection experiment
suggestions (spec Phase 67)." This phase is exactly RQ6's own missing first
step -- `docs/research/research_questions.md`'s RQ6 experiment design opens
with "for each candidate critical component identified by criticality
analysis (Phase 55)..." -- this module supplies that candidate-selection
step for real, closing the loop back to Phase 59 (real injection) and
Phase 63 (predicted-vs-actual validation).

`backend/app/models/experiment.py`'s `Experiment` schema is unsuited for a
not-yet-run recommendation: `random_seed`, `code_version`, `dataset_version`,
`timestamp`, and `environment` are all required with no default, since it
models an executed/about-to-execute run record, not a recommendation. This
module returns its own plain `@dataclass(frozen=True)` instead, matching the
"no new Pydantic schema unless truly a Phase-04-reserved contract" precedent
every prior no-schema phase already followed.

Lives in `backend/dependency/`, not `backend/simulation/`: its only real
input is Phase 55's `GraphCriticalityReport` (a `backend/dependency/` type),
and its output (`FailureScenario`) has no tie to any `backend/simulation/`
pipeline result type -- unlike Phase 61/62/66, which each lived beside the
`backend/simulation/` result type they consumed and extended.

FR-1.39 gives one example (articulation point -> removal experiment) but
phrases the requirement generically ("recommendations," plural, from
"measurable structural evidence," not singular). This module generalizes to
two well-justified, evidence-grounded categories, both derived purely from
Phase 55's already-real `compute_graph_criticality` output -- no new
algorithm:

1. **Structural single point of failure** -- every node where
   `is_articulation_point` is `True` (FR-1.39's own literal example).
   Suggests a `NODE_FAILURE` `FailureScenario`. Ranked by
   `path_dependency_impact` descending -- a real measured severity (how many
   other nodes would actually be stranded), not an invented score.
2. **Routing chokepoint** -- every node that is NOT an articulation point but
   whose `betweenness_centrality` exceeds the graph's own mean betweenness
   across all nodes. A self-relative threshold, not an arbitrary constant,
   matching this codebase's strong preference for non-magic-number formulas
   (Phase 61/62's own ratio formulas). These nodes are central to routing
   without being a structural cut-vertex -- testing them with a hard failure
   would be uninformative (redundant paths already exist), so this category
   suggests `SERVICE_DEGRADATION` instead of `NODE_FAILURE`: it needs only
   `target_node_id`, with no magnitude field to fabricate a number for
   (unlike `LATENCY_INJECTION`, whose `latency_ms` this module would
   otherwise have to invent out of nothing). Ranked by `betweenness_
   centrality` descending.

Every recommendation's reasoning cites real measured values (`degree_
centrality`, `betweenness_centrality`, `path_dependency_impact`, `mean_
incident_edge_confidence` -- or an honest "no incident edges observed" note
when `None`), never a fabricated number, and always ends with an
unconditional disclaimer (mirroring Phase 48/53's own unconditional-
disclaimer convention) pointing back at Phase 59 (real injection) and
Phase 63 (validation) -- a recommendation is structural evidence, not a
validated prediction.

Never imports `simulator.ground_truth` (spec Sec4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.topology import TopologyGraph
from backend.dependency.criticality import NodeCriticality, compute_graph_criticality

_RECOMMENDATION_DISCLAIMER = (
    "This is a structural-evidence-based recommendation, not a validated prediction -- run the "
    "suggested scenario for real (spec Phase 59) and score it against reality (spec Phase 63) "
    "before treating any predicted impact as confirmed."
)


@dataclass(frozen=True)
class ExperimentRecommendation:
    recommendation_id: str
    node_id: str
    category: str  # "structural_single_point_of_failure" | "routing_chokepoint"
    suggested_scenario: FailureScenario
    reasoning: List[str]
    evidence: NodeCriticality


def _mean_betweenness(node_scores: List[NodeCriticality]) -> float:
    if not node_scores:
        return 0.0
    return sum(ns.betweenness_centrality for ns in node_scores) / len(node_scores)


def _confidence_note(ns: NodeCriticality) -> str:
    if ns.mean_incident_edge_confidence is None:
        return f"{ns.node_id} has no incident edges observed; this recommendation rests on graph structure alone."
    return f"mean_incident_edge_confidence={ns.mean_incident_edge_confidence:.3f} across {ns.node_id}'s incident edges."


def generate_experiment_recommendations(graph: TopologyGraph) -> List[ExperimentRecommendation]:
    """Generates real-evidence experiment recommendations from `graph`'s
    Phase 55 criticality report. Never mutates `graph`. Returns `[]` for a
    graph with no qualifying nodes -- never an error.
    """
    report = compute_graph_criticality(graph)
    mean_betweenness = _mean_betweenness(report.node_scores)

    articulation_candidates = sorted(
        (ns for ns in report.node_scores if ns.is_articulation_point),
        key=lambda ns: (-ns.path_dependency_impact, ns.node_id),
    )
    chokepoint_candidates = sorted(
        (
            ns
            for ns in report.node_scores
            if not ns.is_articulation_point and ns.betweenness_centrality > mean_betweenness
        ),
        key=lambda ns: (-ns.betweenness_centrality, ns.node_id),
    )

    recommendations: List[ExperimentRecommendation] = []
    index = 0

    for ns in articulation_candidates:
        index += 1
        reasoning = [
            f"{ns.node_id} is a structural articulation point: removing it would disconnect the graph.",
            f"path_dependency_impact={ns.path_dependency_impact} other node(s) would be stranded "
            "from the main remaining component.",
            f"degree_centrality={ns.degree_centrality:.3f}, betweenness_centrality={ns.betweenness_centrality:.3f}.",
            _confidence_note(ns),
            _RECOMMENDATION_DISCLAIMER,
        ]
        recommendations.append(
            ExperimentRecommendation(
                recommendation_id=f"{graph.graph_id}:recommendation:{index}",
                node_id=ns.node_id,
                category="structural_single_point_of_failure",
                suggested_scenario=FailureScenario(
                    scenario_id=f"{graph.graph_id}:recommended-scenario:{index}",
                    failure_type=FailureType.NODE_FAILURE,
                    target_node_id=ns.node_id,
                ),
                reasoning=reasoning,
                evidence=ns,
            )
        )

    for ns in chokepoint_candidates:
        index += 1
        reasoning = [
            f"{ns.node_id} lies on more shortest communication paths than average for this graph "
            f"(betweenness_centrality={ns.betweenness_centrality:.3f} > graph mean "
            f"{mean_betweenness:.3f}), a likely routing/proxy chokepoint, though not a structural "
            "single point of failure (redundant paths exist).",
            f"degree_centrality={ns.degree_centrality:.3f}.",
            _confidence_note(ns),
            _RECOMMENDATION_DISCLAIMER,
        ]
        recommendations.append(
            ExperimentRecommendation(
                recommendation_id=f"{graph.graph_id}:recommendation:{index}",
                node_id=ns.node_id,
                category="routing_chokepoint",
                suggested_scenario=FailureScenario(
                    scenario_id=f"{graph.graph_id}:recommended-scenario:{index}",
                    failure_type=FailureType.SERVICE_DEGRADATION,
                    target_node_id=ns.node_id,
                ),
                reasoning=reasoning,
                evidence=ns,
            )
        )

    return recommendations
