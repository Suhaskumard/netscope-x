"""Service role inference: a Naive-Bayes-style classifier (spec Phase 36, FR-1.14).

Implements exactly the algorithm `docs/architecture/algorithm_selection.md`
§2 already selected: a Naive-Bayes-style probabilistic classifier over
engineered behavioral features, producing a calibrated-*shape* (but not
yet calibration-*validated*, see below) posterior via Bayes' rule,
directly compatible with the `RoleClassification` schema.

Feature engineering, mapping §2's named feature families onto
`BehavioralFingerprint`'s real fields (Phase 33-35):
  - Continuous (per-role Gaussian): `distinct_destinations`,
    `mean_flow_duration_seconds`, `outbound_byte_ratio`, and
    `port_count = len(distinct_ports)` as the honest proxy for "port set
    entropy" -- `BehavioralFingerprint` only carries the *set* of ports
    observed, not per-port usage frequency, so true Shannon entropy isn't
    computable from this schema; a stated simplification, not silently
    assumed.
  - Binary (per-role Bernoulli): `is_persistent_talker` (persistence),
    protocol-presence flags over {TCP, UDP, ICMP, OTHER} (protocol mix),
    and well-known-port-presence flags reusing the exact same 5 ports
    already established by Phase 26's `backend/nettrace/fingerprint.py`
    table (80/443/5432/6379/53) -- not a new, unjustified port
    vocabulary.

`fit_role_model` takes already-labeled data as a plain parameter -- it
never reads `simulator.ground_truth` itself (trivially compliant with
`scripts/check_ground_truth_boundary.py` regardless of location).
Producing a REAL labeled training set from the Docker lab is a separate,
later concern this phase does not attempt (no Docker in this session's
environment) -- every test in this repo instead uses synthetic labeled
fixtures, the same way every other phase's tests use synthetic
`Flow`/`Packet` fixtures. No model trained on real data is shipped here,
and `GET /behaviors/{node_id}` stays unwired. See
`docs/architecture/service_role_inference.md`.

This produces a real, genuinely-computed posterior -- never a fabricated
or hard label -- but "calibrated" in FR-1.14's sense (predicted
confidence matching observed correctness frequency) requires ground-
truth-scored evaluation, which is explicitly Phase 37's job, not
performed here.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.app.models.behavior import BehavioralFingerprint, RoleClassification, ServiceRole

_PROTOCOLS: Tuple[str, ...] = ("TCP", "UDP", "ICMP", "OTHER")

# Same 5 well-known ports as backend/nettrace/fingerprint.py's Phase 26 table
# (http/tls/postgresql/redis/dns) -- reused here as presence features rather
# than re-derived, to avoid inventing a new, unjustified port vocabulary.
_WELL_KNOWN_PORTS: Tuple[int, ...] = (80, 443, 5432, 6379, 53)


def _continuous_features(fp: BehavioralFingerprint) -> Dict[str, float]:
    return {
        "distinct_destinations": float(fp.distinct_destinations),
        "mean_flow_duration_seconds": fp.mean_flow_duration_seconds,
        "outbound_byte_ratio": fp.outbound_byte_ratio,
        "port_count": float(len(fp.distinct_ports)),
    }


def _binary_features(fp: BehavioralFingerprint) -> Dict[str, bool]:
    protocols = set(fp.distinct_protocols)
    ports = set(fp.distinct_ports)
    features: Dict[str, bool] = {"is_persistent_talker": fp.is_persistent_talker}
    for proto in _PROTOCOLS:
        features[f"protocol_{proto}"] = proto in protocols
    for port in _WELL_KNOWN_PORTS:
        features[f"port_{port}"] = port in ports
    return features


def _gaussian_log_pdf(x: float, mean: float, variance: float) -> float:
    return -0.5 * math.log(2 * math.pi * variance) - ((x - mean) ** 2) / (2 * variance)


@dataclass(frozen=True)
class RoleModel:
    """Fitted Naive Bayes parameters: per-role priors, per-role/feature
    Gaussian (mean, variance) for continuous features, and per-role/feature
    Bernoulli probability for binary features."""

    roles: Tuple[ServiceRole, ...]
    priors: Dict[ServiceRole, float]
    continuous_mean: Dict[ServiceRole, Dict[str, float]]
    continuous_variance: Dict[ServiceRole, Dict[str, float]]
    binary_probability: Dict[ServiceRole, Dict[str, float]]


def fit_role_model(
    labeled: List[Tuple[BehavioralFingerprint, ServiceRole]],
    variance_floor: float = 1e-6,
    laplace_smoothing: float = 1.0,
) -> RoleModel:
    """Fits class-conditional feature likelihoods from `labeled`
    (fingerprint, true role) pairs. Raises `ValueError` on empty input --
    unlike other FLOWMIND functions' "honest zero" convention for missing
    evidence, a classifier genuinely cannot be fit from nothing.

    `variance_floor` prevents a divide-by-zero when a role's training
    sample has identical values for some continuous feature (e.g. a single
    training example). `laplace_smoothing` (add-one-style) prevents a
    binary feature from locking in an exact 0.0/1.0 probability from a
    small or unanimous sample, which would otherwise make one contrary
    observation infinitely improbable.
    """
    if not labeled:
        raise ValueError("fit_role_model requires at least one labeled example")

    by_role: Dict[ServiceRole, List[BehavioralFingerprint]] = defaultdict(list)
    for fingerprint, role in labeled:
        by_role[role].append(fingerprint)

    total = len(labeled)
    roles = tuple(by_role.keys())
    priors = {role: len(fps) / total for role, fps in by_role.items()}

    continuous_mean: Dict[ServiceRole, Dict[str, float]] = {}
    continuous_variance: Dict[ServiceRole, Dict[str, float]] = {}
    binary_probability: Dict[ServiceRole, Dict[str, float]] = {}

    for role, fps in by_role.items():
        cont_values: Dict[str, List[float]] = defaultdict(list)
        bin_values: Dict[str, List[bool]] = defaultdict(list)
        for fp in fps:
            for name, value in _continuous_features(fp).items():
                cont_values[name].append(value)
            for name, value in _binary_features(fp).items():
                bin_values[name].append(value)

        continuous_mean[role] = {name: statistics.fmean(values) for name, values in cont_values.items()}
        continuous_variance[role] = {
            name: max(statistics.pvariance(values), variance_floor) for name, values in cont_values.items()
        }
        binary_probability[role] = {
            name: (sum(values) + laplace_smoothing) / (len(values) + 2 * laplace_smoothing)
            for name, values in bin_values.items()
        }

    return RoleModel(
        roles=roles,
        priors=priors,
        continuous_mean=continuous_mean,
        continuous_variance=continuous_variance,
        binary_probability=binary_probability,
    )


def classify_node_role(
    model: RoleModel,
    fingerprint: BehavioralFingerprint,
    computed_at: Optional[datetime] = None,
) -> RoleClassification:
    """Computes a real posterior over `model.roles` for `fingerprint` via
    Bayes' rule (log-prior + summed per-feature log-likelihoods, Gaussian
    for continuous features and Bernoulli for binary features), normalized
    by a numerically-stable softmax. Returns a genuine `RoleClassification`
    -- its own Phase 04 validator (sums to ~1.0, each value in [0,1]) is
    the real acceptance test for this function's output, not re-implemented
    here.
    """
    continuous = _continuous_features(fingerprint)
    binary = _binary_features(fingerprint)

    log_posteriors: Dict[ServiceRole, float] = {}
    for role in model.roles:
        log_p = math.log(model.priors[role])
        for name, value in continuous.items():
            mean = model.continuous_mean[role][name]
            variance = model.continuous_variance[role][name]
            log_p += _gaussian_log_pdf(value, mean, variance)
        for name, value in binary.items():
            p = model.binary_probability[role][name]
            log_p += math.log(p) if value else math.log(1 - p)
        log_posteriors[role] = log_p

    max_log = max(log_posteriors.values())
    unnormalized = {role: math.exp(lp - max_log) for role, lp in log_posteriors.items()}
    total = sum(unnormalized.values())
    role_probabilities = {role: value / total for role, value in unnormalized.items()}

    return RoleClassification(
        node_id=fingerprint.node_id,
        computed_at=computed_at or datetime.now(timezone.utc),
        role_probabilities=role_probabilities,
    )
