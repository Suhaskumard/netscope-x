"""Does a real threshold crossing trigger a real, observable alert? (spec addendum Phase 89)

Controlled failure of the OBSERVED network, end to end through the real components:
  healthy capture -> snapshot S1 -> twin -> `TwinSyncDaemon` (Phase 88) -> `ResilienceMonitorDaemon` -> alert sinks
  target node's packets removed from the capture, reconstruct, snapshot S2 -> daemon syncs -> monitor evaluates
  packets restored, snapshot S3 -> daemon syncs -> monitor evaluates
For each (topology, seed, target) the EXPECTED outcome is computed independently, straight from the two topology graphs
(`state_indicators` on healthy vs failed graph, which a unit test ties to Phase 62's own formulas): a
`connectivity_low` alert is expected iff that ratio is below the threshold. Checked: healthy state raises no alert; the
alert fires iff expected; the alert's reported value equals the independently computed one; it appears in the JSONL sink
file; it resolves after restoration. Latency is wall time from submitting the failed snapshot to the alert being
observed (includes the twin sync). Targets per topology: highest-degree node (most likely to cross) and a lowest-degree
one. Ground truth is not used. Also measures the optional what-if sweep cost.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from backend.archaeology.snapshots import create_snapshot
from backend.digital_twin.daemon import TwinSyncDaemon
from backend.digital_twin.twin import build_digital_twin
from backend.nettrace.reconstruct import reconstruct_flows
from backend.simulation.resilience_monitor import (
    DEFAULT_RULES, SWEEP_RULES, ResilienceMonitor, ResilienceMonitorDaemon, jsonl_sink, state_indicators,
)
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.incremental_topology_benchmark import CAPTURE, scenario_packets

LEVELS: Tuple[str, ...] = ("small", "multi_service", "large", "multi_path")
SEEDS: Tuple[int, ...] = (42, 43)
THRESHOLD = 0.8  # connectivity_low, from DEFAULT_RULES


@dataclass(frozen=True)
class Row:
    level: str
    seed: int
    target: str  # "hub" | "leaf"
    node: str
    nodes: int
    expected_ratio: float
    expected_reachable: float
    expect_alert: bool
    healthy_alerts: int
    fired: bool
    value_matches: bool
    in_jsonl: bool
    resolved: bool
    latency_s: Optional[float]


def _degrees(graph) -> Dict[str, int]:
    deg = {n.node_id: 0 for n in graph.nodes}
    for e in graph.edges:
        deg[e.source_node_id] += 1
        deg[e.target_node_id] += 1
    return deg


def run_case(root: Path, level: str, seed: int, target: str) -> Row:
    work = Path(tempfile.mkdtemp(dir=_scratch(root)))
    try:
        packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
        end = packets[-1].timestamp
        write_jsonl(packets_path(work, CAPTURE), packets)
        reconstruct_flows(work, CAPTURE)
        s1 = create_snapshot(work, CAPTURE, captured_at=end + timedelta(seconds=1))
        twin0 = build_digital_twin(work, CAPTURE, s1)
        healthy = twin0.topology
        deg = _degrees(healthy)
        order = sorted(deg, key=lambda k: (deg[k], k))
        node_id = order[-1] if target == "hub" else order[0]
        node = next(n for n in healthy.nodes if n.node_id == node_id)
        ips = {str(ip) for ip in node.ip_addresses}
        failed_packets = [p for p in packets if str(p.src_ip) not in ips and str(p.dst_ip) not in ips]

        alert_times: List[Tuple[str, float]] = []
        jsonl = work / "alerts.jsonl"
        monitor = ResilienceMonitor(
            healthy, DEFAULT_RULES,
            sinks=[jsonl_sink(jsonl), lambda a: alert_times.append((a.kind, time.perf_counter()))],
        )
        mon_d = ResilienceMonitorDaemon(monitor)
        sync_d = TwinSyncDaemon(work, twin0, coalesce=False, on_sync=lambda r: mon_d.notify(r.twin))
        mon_d.start()
        sync_d.start()
        mon_d.notify(twin0)
        mon_d.wait_idle()
        healthy_alerts = len(monitor.alerts)

        write_jsonl(packets_path(work, CAPTURE), failed_packets)
        reconstruct_flows(work, CAPTURE)
        s2 = create_snapshot(work, CAPTURE, captured_at=end + timedelta(seconds=2))
        t0 = time.perf_counter()
        sync_d.submit(s2)
        sync_d.wait_idle(120)
        mon_d.wait_idle(120)
        exp = state_indicators(healthy, sync_d.twin.topology)
        expect_alert = exp["connectivity_ratio"] < THRESHOLD
        fired_alert = next((a for a in monitor.alerts if a.rule == "connectivity_low" and a.kind == "fired"), None)
        latency = None
        if fired_alert is not None:
            latency = next(t for k, t in alert_times if k == "fired") - t0

        write_jsonl(packets_path(work, CAPTURE), packets)
        reconstruct_flows(work, CAPTURE)
        s3 = create_snapshot(work, CAPTURE, captured_at=end + timedelta(seconds=3))
        sync_d.submit(s3)
        sync_d.wait_idle(120)
        mon_d.wait_idle(120)
        sync_d.stop()
        mon_d.stop()

        rows = [json.loads(line) for line in jsonl.read_text().splitlines()] if jsonl.exists() else []
        fired_rules = {a.rule for a in monitor.alerts if a.kind == "fired"}
        resolved = not monitor.active and all(
            any(a.rule == r and a.kind == "resolved" for a in monitor.alerts) for r in fired_rules
        )
        return Row(
            level, seed, target, node_id, len(healthy.nodes), exp["connectivity_ratio"], exp["reachable_node_ratio"],
            expect_alert, healthy_alerts, fired_alert is not None,
            fired_alert is not None and abs(fired_alert.value - exp["connectivity_ratio"]) < 1e-12,
            len(rows) == len(monitor.alerts), resolved, latency,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_matrix(root: Path, levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS) -> List[Row]:
    return [run_case(root, lv, sd, tg) for lv in levels for sd in seeds for tg in ("hub", "leaf")]


def _scratch(root: Path) -> Path:
    p = root / "resilience_monitor_scratch"
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_matrix(rows: Sequence[Row]) -> str:
    out = [f"{'level':<14}{'seed':>5} {'tgt':<5}{'nodes':>6}{'conn':>7}{'reach':>7}{'expect':>7}{'fired':>6}"
           f"{'val==':>6}{'jsonl':>6}{'resolv':>7}{'healthy':>8}{'lat_s':>7}"]
    for r in rows:
        out.append(f"{r.level:<14}{r.seed:>5} {r.target:<5}{r.nodes:>6}{r.expected_ratio:>7.3f}"
                   f"{r.expected_reachable:>7.3f}{str(r.expect_alert):>7}{str(r.fired):>6}"
                   f"{str(r.value_matches) if r.fired else '-':>6}{str(r.in_jsonl):>6}"
                   f"{str(r.resolved) if r.fired else '-':>7}{r.healthy_alerts:>8}"
                   f"{('-' if r.latency_s is None else f'{r.latency_s:.2f}'):>7}")
    fired = [r for r in rows if r.fired]
    crossed = [r for r in rows if r.expect_alert]
    lat = [r.latency_s for r in rows if r.latency_s is not None]
    out.append(
        f"\nfired == expected: {sum(r.fired == r.expect_alert for r in rows)}/{len(rows)}; "
        f"crossings expected {len(crossed)}, detected {sum(r.fired for r in crossed)}; "
        f"false alerts on healthy state {sum(r.healthy_alerts for r in rows)}; "
        f"value equals independent computation {sum(r.value_matches for r in fired)}/{len(fired)}; "
        f"resolved after restore {sum(r.resolved for r in fired)}/{len(fired)}; "
        f"in JSONL {sum(r.in_jsonl for r in rows)}/{len(rows)}"
        + (f"; latency (submit->alert, incl. twin sync) median {median(lat):.2f} s, max {max(lat):.2f} s" if lat else "")
    )
    return "\n".join(out)


def sweep_cost(root: Path, levels: Sequence[str] = ("small", "multi_service", "large")) -> str:
    """Cost of one what-if sweep (every single node/edge failure) over a healthy twin."""
    lines = []
    for level in levels:
        work = Path(tempfile.mkdtemp(dir=_scratch(root)))
        try:
            packets = sorted(scenario_packets(level, 42), key=lambda p: p.timestamp)
            write_jsonl(packets_path(work, CAPTURE), packets)
            reconstruct_flows(work, CAPTURE)
            snap = create_snapshot(work, CAPTURE, captured_at=packets[-1].timestamp + timedelta(seconds=1))
            twin = build_digital_twin(work, CAPTURE, snap)
            m = ResilienceMonitor(twin.topology, SWEEP_RULES, sweep=True)
            t0 = time.perf_counter()
            m.evaluate(twin)
            dt = time.perf_counter() - t0
            lines.append(f"{level:<14} {m.stats.scenarios_evaluated:>4} scenarios  {dt:>7.2f} s  "
                         f"({dt / max(1, m.stats.scenarios_evaluated) * 1000:.0f} ms/scenario)  "
                         f"{m.stats.fired} sweep alerts on the healthy graph")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return "\n".join(lines)
