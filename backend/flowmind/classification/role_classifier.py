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
or hard label. Phase 37 (`fit_temperature`, plus `classify_node_role`'s
`temperature` parameter) adds real temperature scaling: a single scalar
`T`, fit on held-out labeled data by minimizing negative log-likelihood,
that rescales the posterior (`softmax(log_posteriors / T)`) before
normalization -- flattening an overconfident distribution or sharpening
an underconfident one. This is a genuine, fitted calibration mechanism,
not a hand-picked rescaling. It does NOT by itself prove the result is
calibrated in FR-1.14/RQ2's sense (predicted confidence matching observed
correctness frequency across many real classifications) -- that requires
ground-truth-scored evaluation, which is `experiments/metrics/
role_calibration.py`'s job (evaluation-only, never reachable from here),
and real validation against Docker-lab data remains out of scope this
session (no Docker). See `docs/architecture/uncertainty_aware_classification.md`.
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


def _log_posteriors(model: RoleModel, fingerprint: BehavioralFingerprint) -> Dict[ServiceRole, float]:
    """Real, unnormalized log-posterior per role via Bayes' rule: log-prior
    plus summed per-feature log-likelihoods (Gaussian for continuous
    features, Bernoulli for binary features). Exposed separately from
    `classify_node_role` so Phase 37's temperature scaling can rescale
    these before normalization, without recomputing the Bayes math."""
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
    return log_posteriors


def _softmax(log_values: Dict[ServiceRole, float], temperature: float = 1.0) -> Dict[ServiceRole, float]:
    """Numerically-stable softmax, optionally temperature-scaled
    (`softmax(log_values / temperature)`, spec Phase 37): `temperature > 1`
    flattens the distribution toward uniform (less confident);
    `temperature < 1` sharpens it (more confident); `temperature == 1` is
    the original, unscaled posterior."""
    scaled = {role: lp / temperature for role, lp in log_values.items()}
    max_log = max(scaled.values())
    unnormalized = {role: math.exp(lp - max_log) for role, lp in scaled.items()}
    total = sum(unnormalized.values())
    return {role: value / total for role, value in unnormalized.items()}


def classify_node_role(
    model: RoleModel,
    fingerprint: BehavioralFingerprint,
    computed_at: Optional[datetime] = None,
    temperature: float = 1.0,
) -> RoleClassification:
    """Computes a real posterior over `model.roles` for `fingerprint` via
    Bayes' rule, normalized by a numerically-stable (optionally
    temperature-scaled, spec Phase 37) softmax. `temperature=1.0` (the
    default) reproduces Phase 36's original, unscaled behavior exactly.
    Returns a genuine `RoleClassification` -- its own Phase 04 validator
    (sums to ~1.0, each value in [0,1]) is the real acceptance test for
    this function's output, not re-implemented here.
    """
    log_posteriors = _log_posteriors(model, fingerprint)
    role_probabilities = _softmax(log_posteriors, temperature)

    return RoleClassification(
        node_id=fingerprint.node_id,
        computed_at=computed_at or datetime.now(timezone.utc),
        role_probabilities=role_probabilities,
    )


def _negative_log_likelihood(
    model: RoleModel,
    labeled: List[Tuple[BehavioralFingerprint, ServiceRole]],
    temperature: float,
) -> float:
    total = 0.0
    for fingerprint, true_role in labeled:
        probabilities = _softmax(_log_posteriors(model, fingerprint), temperature)
        # Floored, never zero: an unseen-in-training role would otherwise make
        # a single held-out example's likelihood exactly 0 (log(0) = -inf),
        # which would make grid search reject every candidate temperature.
        total += -math.log(max(probabilities.get(true_role, 0.0), 1e-12))
    return total


def _grid_search_minimize(
    objective, low: float, high: float, grid_size: int
) -> Tuple[float, float]:
    """Evaluates `objective` at `grid_size` log-spaced points in [low, high]
    and returns the (x, value) pair achieving the minimum. A small,
    self-contained substitute for `scipy.optimize` -- this is a
    one-dimensional, well-behaved search that doesn't justify the added
    dependency weight (NFR-9)."""
    log_low, log_high = math.log(low), math.log(high)
    best_x, best_value = low, objective(low)
    for i in range(grid_size):
        x = math.exp(log_low + (log_high - log_low) * i / (grid_size - 1))
        value = objective(x)
        if value < best_value:
            best_x, best_value = x, value
    return best_x, best_value


def fit_temperature(
    model: RoleModel,
    labeled: List[Tuple[BehavioralFingerprint, ServiceRole]],
    bounds: Tuple[float, float] = (0.05, 20.0),
    grid_size: int = 200,
) -> float:
    """Fits a single scalar temperature (spec Phase 37) on held-out labeled
    data by minimizing the negative log-likelihood of the true role under
    the temperature-scaled posterior -- a real, fitted correction, not an
    arbitrary rescaling (the same "no principled basis to weight things
    arbitrarily" reasoning already established for Phase 31's edge-
    confidence signals). Raises `ValueError` on empty input, mirroring
    `fit_role_model`: a temperature cannot be fit from nothing.

    Two-pass log-spaced grid search: a coarse pass over the full `bounds`,
    then a refined pass narrowed around the coarse optimum -- deterministic
    and dependency-free (see `_grid_search_minimize`).
    """
    if not labeled:
        raise ValueError("fit_temperature requires at least one labeled example")

    def objective(temperature: float) -> float:
        return _negative_log_likelihood(model, labeled, temperature)

    low, high = bounds
    coarse_t, _ = _grid_search_minimize(objective, low, high, grid_size)

    refined_low = max(low, coarse_t * 0.5)
    refined_high = min(high, coarse_t * 2.0)
    if refined_low >= refined_high:
        return coarse_t
    refined_t, _ = _grid_search_minimize(objective, refined_low, refined_high, grid_size)
    return refined_t


# Phase 84 hardening. A continuous feature's scale is floored at this fraction of its (role) mean magnitude so a
# role fitted from one or two nodes (near-zero variance) does not call every clean node out-of-distribution.
# Provisional and evidence-light, like the other floors in this file; the benchmark reports its clean abstain rate.
_OOD_RELATIVE_SCALE_FLOOR = 0.1


def is_out_of_distribution(model: RoleModel, fingerprint: BehavioralFingerprint, max_feature_z: float = 4.0) -> bool:
    """True if some continuous feature of `fingerprint` lies more than `max_feature_z` scale units from EVERY
    role's mean -- behavior no known role produces (e.g. crafted mimicry that matches no one role's profile)."""
    for name, value in _continuous_features(fingerprint).items():
        nearest = min(
            abs(value - model.continuous_mean[role][name])
            / max(
                math.sqrt(model.continuous_variance[role][name]),
                _OOD_RELATIVE_SCALE_FLOOR * max(abs(model.continuous_mean[role][name]), 1.0),
            )
            for role in model.roles
        )
        if nearest > max_feature_z:
            return True
    return False


def classify_node_role_robust(
    model: RoleModel,
    fingerprint: BehavioralFingerprint,
    computed_at: Optional[datetime] = None,
    temperature: float = 1.0,
    max_feature_z: float = 4.0,
) -> RoleClassification:
    """`classify_node_role`, but a fingerprint that `is_out_of_distribution` gets a uniform posterior over
    `model.roles` (an honest "cannot tell") instead of a confident wrong role. Inputs that are in distribution
    give exactly `classify_node_role`'s result."""
    if not is_out_of_distribution(model, fingerprint, max_feature_z):
        return classify_node_role(model, fingerprint, computed_at, temperature)
    uniform = {role: 1.0 / len(model.roles) for role in model.roles}
    return RoleClassification(
        node_id=fingerprint.node_id,
        computed_at=computed_at or datetime.now(timezone.utc),
        role_probabilities=uniform,
    )
