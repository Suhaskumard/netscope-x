"""NETSCOPE-X shared data contracts (spec Phase 04).

Every pipeline module (NETTRACE, FLOWMIND, Archaeology, Causal, PathForge,
Counterfactual, Experiments) and the API layer import schemas from here
rather than redefining their own -- this is the single source of truth for
cross-module data shapes.
"""

from backend.app.models.anomaly import Anomaly, AnomalyClass, AnomalyDimension
from backend.app.models.behavior import (
    BehavioralFingerprint,
    ObservationWindow,
    RoleClassification,
    ServiceRole,
)
from backend.app.models.dependency import (
    CausalEvidenceReport,
    CommunicationRelationship,
    DependencyEdge,
)
from backend.app.models.experiment import Experiment
from backend.app.models.failure import (
    FailureScenario,
    FailureType,
    ImpactOrder,
    PropagationImpact,
    ResilienceIndicators,
)
from backend.app.models.flow import Flow, FlowFeatures, TCPState
from backend.app.models.metric import MetricContext, MetricResult
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.simulation import (
    CounterfactualAction,
    CounterfactualScenario,
    SimulationRun,
)
from backend.app.models.snapshot import ChangeType, GraphChangeEvent, NetworkSnapshot
from backend.app.models.topology import Edge, Node, TopologyGraph

__all__ = [
    "Anomaly",
    "AnomalyClass",
    "AnomalyDimension",
    "BehavioralFingerprint",
    "ObservationWindow",
    "RoleClassification",
    "ServiceRole",
    "CausalEvidenceReport",
    "CommunicationRelationship",
    "DependencyEdge",
    "Experiment",
    "FailureScenario",
    "FailureType",
    "ImpactOrder",
    "PropagationImpact",
    "ResilienceIndicators",
    "Flow",
    "FlowFeatures",
    "TCPState",
    "MetricContext",
    "MetricResult",
    "Packet",
    "PacketDirection",
    "TransportProtocol",
    "CounterfactualAction",
    "CounterfactualScenario",
    "SimulationRun",
    "ChangeType",
    "GraphChangeEvent",
    "NetworkSnapshot",
    "Edge",
    "Node",
    "TopologyGraph",
]
