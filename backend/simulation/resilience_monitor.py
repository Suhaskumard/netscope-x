"""Real-Time Resilience Monitoring Backend (spec addendum Phase 89).

Continuously turns live twin state into Phase 62 resilience indicators and alerts on threshold crossings. Two kinds
of reading, kept distinct because they answer different questions:

- "state": what the OBSERVED topology looks like now against a healthy reference (`connectivity_ratio`,
  `reachable_node_ratio`). Phase 62 only accepts injected `FailureScenario`s (before/after are both derived from one
  graph), so a real outage in the live graph needs the same two ratios over reference -> live. They use Phase 62's
  exact formulas (largest-component share; share of reference nodes in a component of >= 2); a test checks they equal
  `compute_resilience_indicators` when the live graph is a scenario's post-failure graph. Nodes missing from the live
  graph count as unreachable.
- "sweep" (optional, expensive): what WOULD happen under each single node/edge failure of the live graph, straight
  from `run_failure_propagation_pipeline` + `compute_resilience_indicators` (all six indicators). These are risk
  findings, not outages.

Alerts are edge-triggered per (rule, scope): one `fired` on crossing, silence while breached, one `resolved` when the
value clears the threshold by `clear_margin`. Default thresholds are PROVISIONAL (chosen, not calibrated).

Limits: in-process, one evaluator thread; the sweep costs one full pipeline per scenario per evaluation; alerts are
in memory plus an optional JSONL sink; no persistence of monitor state; latest-wins (a twin superseded before it was
evaluated is skipped).

Never imports `simulator.ground_truth` (spec §4).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend.app.models.failure import FailureScenario, FailureType, ResilienceIndicators
from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.digital_twin.twin import DigitalTwin
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.path_engine import compute_connectivity
from backend.simulation.resilience_indicators import compute_resilience_indicators

STATE = "state"
SWEEP = "sweep"
OPS = ("lt", "gt", "is_false", "nonempty")


@dataclass(frozen=True)
class AlertRule:
    name: str
    indicator: str  # a ResilienceIndicators field (sweep) or connectivity_ratio / reachable_node_ratio (state)
    op: str  # lt | gt | is_false | nonempty
    threshold: float = 0.0
    severity: str = "warning"
    scope: str = STATE
    clear_margin: float = 0.0  # hysteresis: lt clears at >= threshold + margin, gt at <= threshold - margin


DEFAULT_RULES: Tuple[AlertRule, ...] = (  # provisional
    AlertRule("connectivity_low", "connectivity_ratio", "lt", 0.8, "critical", STATE, 0.05),
    AlertRule("reachable_nodes_low", "reachable_node_ratio", "lt", 0.8, "warning", STATE, 0.05),
)
SWEEP_RULES: Tuple[AlertRule, ...] = (  # provisional; single points of failure in the live graph
    AlertRule("spof_connectivity", "connectivity_ratio", "lt", 0.5, "warning", SWEEP, 0.05),
    AlertRule("spof_no_alternate_path", "alternative_path_available", "is_false", 0.0, "info", SWEEP),
)


@dataclass(frozen=True)
class Alert:
    rule: str
    scope_id: str  # "state" or the sweep scenario_id
    kind: str  # fired | resolved
    indicator: str
    value: Any  # None when a sweep scenario disappeared
    threshold: float
    severity: str
    at: str  # ISO wall-clock time
    evaluation: int


@dataclass
class MonitorStats:
    evaluations: int = 0
    fired: int = 0
    resolved: int = 0
    scenarios_evaluated: int = 0
    eval_seconds: List[float] = field(default_factory=list)


def _breached(rule: AlertRule, value: Any) -> bool:
    if rule.op == "lt":
        return value < rule.threshold
    if rule.op == "gt":
        return value > rule.threshold
    if rule.op == "is_false":
        return value is False
    return bool(value)  # nonempty


def _cleared(rule: AlertRule, value: Any) -> bool:
    if rule.op == "lt":
        return value >= rule.threshold + rule.clear_margin
    if rule.op == "gt":
        return value <= rule.threshold - rule.clear_margin
    return not _breached(rule, value)


def state_indicators(reference: TopologyGraph, live: TopologyGraph) -> Dict[str, float]:
    """Phase 62's connectivity_ratio / reachable_node_ratio over a reference -> live change."""
    before, after = compute_connectivity(reference), compute_connectivity(live)
    before_size = len(before.largest_component_node_ids)
    ref_nodes = {n for comp in before.components for n in comp}
    reachable = {n for comp in after.components if len(comp) >= 2 for n in comp}
    return {
        "connectivity_ratio": 1.0 if before_size == 0 else len(after.largest_component_node_ids) / before_size,
        "reachable_node_ratio": 1.0 if not ref_nodes else len(reachable & ref_nodes) / len(ref_nodes),
    }


def sweep_scenarios(graph: TopologyGraph, max_scenarios: Optional[int] = None) -> List[FailureScenario]:
    scenarios = [
        FailureScenario(scenario_id=f"node:{n.node_id}", failure_type=FailureType.NODE_FAILURE, target_node_id=n.node_id)
        for n in sorted(graph.nodes, key=lambda n: n.node_id)
    ] + [
        FailureScenario(scenario_id=f"edge:{e.edge_id}", failure_type=FailureType.EDGE_FAILURE, target_edge_id=e.edge_id)
        for e in sorted(graph.edges, key=lambda e: e.edge_id)
    ]
    return scenarios if max_scenarios is None else scenarios[:max_scenarios]


def _indicator_value(ind: ResilienceIndicators, name: str) -> Any:
    value = getattr(ind, name)
    return len(value) if isinstance(value, list) else value


def jsonl_sink(path: Path) -> Callable[[Alert], None]:
    lock = threading.Lock()
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(alert: Alert) -> None:
        with lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(alert)) + "\n")

    return write


class ResilienceMonitor:
    def __init__(
        self,
        reference: Optional[TopologyGraph] = None,
        rules: Sequence[AlertRule] = DEFAULT_RULES,
        *,
        sweep: bool = False,
        max_scenarios: Optional[int] = None,
        sinks: Sequence[Callable[[Alert], None]] = (),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        for r in rules:
            if r.op not in OPS or r.scope not in (STATE, SWEEP):
                raise ValueError(f"bad rule {r.name}")
        self._reference = reference
        self._rules = list(rules)
        self._sweep = sweep
        self._max = max_scenarios
        self._sinks = list(sinks)
        self._now = now
        self._active: Dict[Tuple[str, str], Any] = {}  # (rule, scope_id) -> last breached value
        self.alerts: List[Alert] = []
        self.stats = MonitorStats()
        self.last_state: Dict[str, float] = {}
        self.last_sweep: Dict[str, ResilienceIndicators] = {}

    def evaluate(self, twin: DigitalTwin) -> List[Alert]:
        """One evaluation over `twin`'s topology; returns the alerts (fired/resolved) it produced."""
        t0 = time.perf_counter()
        graph = twin.topology
        if self._reference is None:
            self._reference = graph  # first reading defines "healthy"
        self.stats.evaluations += 1
        seen: set = set()
        produced: List[Alert] = []

        state = state_indicators(self._reference, graph)
        self.last_state = state
        for rule in (r for r in self._rules if r.scope == STATE):
            produced += self._judge(rule, STATE, state[rule.indicator], seen)

        sweep_rules = [r for r in self._rules if r.scope == SWEEP]
        if self._sweep and sweep_rules:
            candidates = generate_causal_candidates(twin.dependencies)
            self.last_sweep = {}
            for sc in sweep_scenarios(graph, self._max):
                ind = compute_resilience_indicators(
                    graph, run_failure_propagation_pipeline(graph, sc, candidates)
                )
                self.last_sweep[sc.scenario_id] = ind
                self.stats.scenarios_evaluated += 1
                for rule in sweep_rules:
                    produced += self._judge(rule, sc.scenario_id, _indicator_value(ind, rule.indicator), seen)

        # a scope that no longer exists (e.g. a removed node's scenario) resolves its alerts
        for key in [k for k in self._active if k not in seen]:
            rule = next(r for r in self._rules if r.name == key[0])
            produced.append(self._emit(rule, key[1], "resolved", None))
            del self._active[key]
        self.stats.eval_seconds.append(time.perf_counter() - t0)
        return produced

    def _judge(self, rule: AlertRule, scope_id: str, value: Any, seen: set) -> List[Alert]:
        key = (rule.name, scope_id)
        if key in self._active:
            if _cleared(rule, value):
                del self._active[key]
                return [self._emit(rule, scope_id, "resolved", value)]
            seen.add(key)
            return []
        if _breached(rule, value):
            self._active[key] = value
            seen.add(key)
            return [self._emit(rule, scope_id, "fired", value)]
        return []

    def _emit(self, rule: AlertRule, scope_id: str, kind: str, value: Any) -> Alert:
        alert = Alert(rule.name, scope_id, kind, rule.indicator, value, rule.threshold, rule.severity,
                      self._now().isoformat(), self.stats.evaluations)
        self.alerts.append(alert)
        if kind == "fired":
            self.stats.fired += 1
        else:
            self.stats.resolved += 1
        for sink in self._sinks:
            sink(alert)
        return alert

    @property
    def active(self) -> List[Tuple[str, str]]:
        return sorted(self._active)


class ResilienceMonitorDaemon:
    """Evaluates the most recent twin handed to `notify` on a worker thread. Latest-wins: a twin superseded before
    the worker picks it up is skipped; the same twin object is never evaluated twice. `min_interval` spaces
    evaluations. Wire to Phase 88 with `TwinSyncDaemon(..., on_sync=lambda r: daemon.notify(r.twin))`."""

    def __init__(self, monitor: ResilienceMonitor, min_interval: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.monitor = monitor
        self._min_interval, self._clock, self._sleep = min_interval, clock, sleep
        self._cv = threading.Condition()
        self._pending: Optional[DigitalTwin] = None
        self._last: Optional[DigitalTwin] = None
        self._stop = False
        self._busy = False
        self._thread: Optional[threading.Thread] = None
        self.skipped_superseded = 0
        self.skipped_unchanged = 0
        self.errors: List[str] = []

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("daemon already started")
        self._thread = threading.Thread(target=self._run, name="resilience-monitor", daemon=True)
        self._thread.start()

    def notify(self, twin: DigitalTwin) -> None:
        with self._cv:
            if twin is self._last and self._pending is None:
                self.skipped_unchanged += 1
                return
            if self._pending is not None:
                self.skipped_superseded += 1
            self._pending = twin
            self._cv.notify()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._pending is not None or self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(min(left, 0.05))
        return True

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(30)

    def _run(self) -> None:
        last_at = None
        while True:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait(0.05)
                if self._stop and self._pending is None:
                    return
                twin, self._pending, self._busy = self._pending, None, True
            try:
                if last_at is not None and self._min_interval:
                    wait = self._min_interval - (self._clock() - last_at)
                    if wait > 0:
                        self._sleep(wait)
                self.monitor.evaluate(twin)
                last_at = self._clock()
            except Exception as exc:  # noqa: BLE001 - keep monitoring
                self.errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                with self._cv:
                    self._last, self._busy = twin, False
                    self._cv.notify_all()
