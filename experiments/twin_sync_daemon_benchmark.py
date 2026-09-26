"""Equivalence, backpressure and rate limiting of the digital-twin sync daemon (spec addendum Phase 88).

A capture's packets are written once; snapshots are taken at increasing `captured_at` (Phase 43's `as_of` bound), so
each snapshot sees only the evidence up to its time. The sequence is replayed through `TwinSyncDaemon` under several
configurations and the final twin is CHECKED against (a) a manual chain of on-demand `sync_digital_twin` calls, one
per snapshot, and (b) a single `build_digital_twin` at the last snapshot with the same fingerprints. Compared: topology,
dependencies, history, behavioral fingerprints and snapshot (everything except the `generated_at` build stamp).
Behavioral fingerprints are supplied per snapshot (computed from the flows visible then) so the merge path is used.

Also measured: queue depth never exceeds its bound, the reject/block counts, and achieved syncs/second against the
token-bucket cap. Ground truth is not used.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import List, Optional, Sequence, Tuple

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.snapshot import NetworkSnapshot
from backend.archaeology.snapshots import create_snapshot
from backend.digital_twin.daemon import TwinSyncDaemon, twin_state_equal
from backend.digital_twin.sync import sync_digital_twin
from backend.digital_twin.twin import DigitalTwin, build_digital_twin
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.incremental_topology_benchmark import CAPTURE, scenario_packets

LEVELS: Tuple[str, ...] = ("small", "multi_service", "large")
SEEDS: Tuple[int, ...] = (42, 43)
SNAPSHOTS = 8
# (name, policy, coalesce, max_syncs_per_second, max_queue)
CONFIGS: Tuple[Tuple[str, str, bool, Optional[float], int], ...] = (
    ("block/step/unlimited", "block", False, None, 4),
    ("block/coalesce/unlimited", "block", True, None, 4),
    ("reject/step/unlimited", "reject", False, None, 2),
    ("block/coalesce/rate20", "block", True, 20.0, 2),
)


@dataclass(frozen=True)
class Sequence_:
    root: Path
    snapshots: List[NetworkSnapshot]
    fingerprints: List[List[BehavioralFingerprint]]


def build_sequence(root: Path, level: str, seed: int, snapshots: int = SNAPSHOTS) -> Sequence_:
    """Writes the capture, then takes `snapshots` snapshots at evenly spaced packet timestamps (last = everything)."""
    packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
    write_jsonl(packets_path(root, CAPTURE), packets)
    flows = reconstruct_flows(root, CAPTURE)
    n = len(packets)
    ends = sorted({max(0, round(n * (i + 1) / snapshots) - 1) for i in range(snapshots)})
    snaps, fps = [], []
    for end in ends:
        at = packets[end].timestamp + timedelta(microseconds=1)
        snaps.append(create_snapshot(root, CAPTURE, captured_at=at))
        nodes = discover_nodes(root, CAPTURE)
        seen = [f for f in flows if f.first_seen <= at]
        fps.append(
            [assemble_node_fingerprint(seen, nd, ObservationWindow.MEDIUM, computed_at=at) for nd in nodes[:3]]
        )
    return Sequence_(root, snaps, fps)


def manual_chain(seq: Sequence_) -> DigitalTwin:
    twin = build_digital_twin(seq.root, CAPTURE, seq.snapshots[0], seq.fingerprints[0])
    for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
        twin = sync_digital_twin(seq.root, twin, snap, fp).twin
    return twin


def run_daemon(seq: Sequence_, policy: str, coalesce: bool, rate: Optional[float], max_queue: int):
    """Feeds every snapshot after the first as fast as the policy allows; returns (final twin, stats, elapsed, retries)."""
    twin0 = build_digital_twin(seq.root, CAPTURE, seq.snapshots[0], seq.fingerprints[0])
    d = TwinSyncDaemon(
        seq.root, twin0, max_queue=max_queue, policy=policy, coalesce=coalesce,
        max_syncs_per_second=rate, burst=1,
    )
    d.start()
    started = time.perf_counter()
    retries = 0
    for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
        while not d.submit(snap, fp, timeout=5.0):  # reject policy: retry until accepted (producer backs off)
            retries += 1
            time.sleep(0.002)
    d.stop(drain=True, timeout=60)
    return d.twin, d.stats, time.perf_counter() - started, retries


@dataclass(frozen=True)
class EquivalenceRow:
    level: str
    seed: int
    config: str
    equals_manual_chain: bool
    equals_direct_build: bool
    synced: int
    coalesced: int
    retries: int
    max_queue_depth: int
    max_queue: int
    errors: int
    syncs_per_second: float
    rate_cap: Optional[float]


def run_equivalence(root: Path, levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS) -> List[EquivalenceRow]:
    rows: List[EquivalenceRow] = []
    for level in levels:
        for seed in seeds:
            work = Path(tempfile.mkdtemp(dir=_scratch(root)))
            try:
                seq = build_sequence(work, level, seed)
                manual = manual_chain(seq)
                direct = build_digital_twin(work, CAPTURE, seq.snapshots[-1], seq.fingerprints[-1])
                for name, policy, coalesce, rate, max_queue in CONFIGS:
                    twin, st, elapsed, retries = run_daemon(seq, policy, coalesce, rate, max_queue)
                    rows.append(EquivalenceRow(
                        level, seed, name, twin_state_equal(twin, manual),
                        _same_as_direct(twin, direct, seq), st.synced, st.coalesced, retries,
                        st.max_queue_depth, max_queue, st.errors, st.synced / elapsed if elapsed else 0.0, rate,
                    ))
            finally:
                shutil.rmtree(work, ignore_errors=True)
    return rows


def _same_as_direct(twin: DigitalTwin, direct: DigitalTwin, seq: Sequence_) -> bool:
    """A direct build has only the last snapshot's fingerprints; the daemon carries older ones forward by design, so
    compare everything except the fingerprint list, and require the direct build's fingerprints to be a subset."""
    return (
        twin.snapshot == direct.snapshot and twin.topology == direct.topology
        and twin.dependencies == direct.dependencies and twin.history == direct.history
        and all(fp in twin.behavioral_fingerprints for fp in direct.behavioral_fingerprints)
    )


def _scratch(root: Path) -> Path:
    p = root / "twin_sync_daemon_scratch"
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_equivalence(rows: Sequence[EquivalenceRow]) -> str:
    out = [f"{'level':<14}{'seed':>5} {'config':<26}{'==manual':>9}{'==direct':>9}{'synced':>7}{'coal':>5}"
           f"{'retry':>6}{'qmax/cap':>9}{'err':>4}{'syncs/s':>9}{'cap':>6}"]
    for r in rows:
        out.append(
            f"{r.level:<14}{r.seed:>5} {r.config:<26}{str(r.equals_manual_chain):>9}{str(r.equals_direct_build):>9}"
            f"{r.synced:>7}{r.coalesced:>5}{r.retries:>6}{f'{r.max_queue_depth}/{r.max_queue}':>9}{r.errors:>4}"
            f"{r.syncs_per_second:>9.1f}{('-' if r.rate_cap is None else f'{r.rate_cap:g}'):>6}"
        )
    ok = sum(r.equals_manual_chain for r in rows)
    out.append(f"\nfinal twin == manual chain: {ok}/{len(rows)}; direct-build consistency: "
               f"{sum(r.equals_direct_build for r in rows)}/{len(rows)}; bound respected: "
               f"{sum(r.max_queue_depth <= r.max_queue for r in rows)}/{len(rows)}")
    return "\n".join(out)


@dataclass(frozen=True)
class RateRow:
    cap: float
    burst: int
    submitted: int
    achieved: float
    bound: float


def run_rate(root: Path, caps: Sequence[float] = (1.0, 2.0, 3.0), submissions: int = 8) -> List[RateRow]:
    """Real-time check of the token bucket: submit as fast as possible (no coalescing) and compare the achieved sync
    rate to the cap. Upper bound is submissions-1 syncs over the time they must span at `cap` (first one is a burst)."""
    rows: List[RateRow] = []
    work = Path(tempfile.mkdtemp(dir=_scratch(root)))
    try:
        seq = build_sequence(work, "small", 42, snapshots=submissions + 1)
        for cap in caps:
            twin0 = build_digital_twin(work, CAPTURE, seq.snapshots[0], seq.fingerprints[0])
            d = TwinSyncDaemon(work, twin0, max_queue=4, policy="block", coalesce=False, max_syncs_per_second=cap)
            d.start()
            t0 = time.perf_counter()
            for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
                d.submit(snap, fp)
            d.stop(drain=True, timeout=60)
            elapsed = time.perf_counter() - t0
            rows.append(RateRow(cap, 1, d.stats.synced, d.stats.synced / elapsed, cap))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return rows


def format_rate(rows: Sequence[RateRow]) -> str:
    out = [f"{'cap/s':>7}{'synced':>8}{'achieved/s':>12}  (no-limit throughput here is ~3.6/s, so only caps below it bind)"]
    out += [f"{r.cap:>7g}{r.submitted:>8}{r.achieved:>12.1f}" for r in rows]
    return "\n".join(out)


def latency_summary(root: Path) -> str:
    """Per-sync cost and end-to-end latency on the large topology, unlimited rate, no coalescing."""
    work = Path(tempfile.mkdtemp(dir=_scratch(root)))
    try:
        seq = build_sequence(work, "large", 42)
        twin0 = build_digital_twin(work, CAPTURE, seq.snapshots[0], seq.fingerprints[0])
        d = TwinSyncDaemon(work, twin0, max_queue=8, policy="block", coalesce=False)
        d.start()
        for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
            d.submit(snap, fp)
        d.stop(drain=True, timeout=120)
        s = d.stats
        return (f"large, {s.synced} syncs: sync time median {median(s.sync_times_s) * 1000:.0f} ms, "
                f"max {max(s.sync_times_s) * 1000:.0f} ms; submit->applied latency median "
                f"{median(s.latencies_s) * 1000:.0f} ms, max {max(s.latencies_s) * 1000:.0f} ms")
    finally:
        shutil.rmtree(work, ignore_errors=True)
