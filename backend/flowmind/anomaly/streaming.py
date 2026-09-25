"""Real-time (streaming) anomaly detection (spec addendum Phase 86).

Batch scoring (Phase 40/76) judges a node only after its whole behavioral window has closed, so detection latency is
at least "time left in the window". `StreamingAnomalyDetector` judges nodes while the window is still open, as packets
arrive, and reuses the very same scoring (`detect_node_anomalies`) and fingerprinting (`assemble_node_fingerprint`)
the batch path uses -- no second detector, so evidence, z-scores and thresholds mean the same thing in both.

How it works
  - Packets go into Phase 85's `IncrementalTopology` (flows re-derived only for touched five-tuples).
  - Time is cut into tumbling windows of `window_seconds` anchored at `anchor` (same epochs as the batch dataset).
    Windows before `scoring_start` are history: ingested, never scored.
  - After each `ingest`, only nodes whose IPs appeared in the chunk are re-fingerprinted over the OPEN window and
    scored against their fixed baseline.
  - A partial window is not a whole window, so while it is open only the checks that stay valid on partial evidence
    are trusted: new ports/protocols and UPWARD deviation of destinations / byte count (those only grow as evidence
    accumulates). Downward deviations and the ratio/duration features need the whole window, so they are judged when
    the window closes (`close_window`, called automatically when a packet of a later window arrives, and by `flush`).
    Every (node, dimension) alerts at most once per window.

Limits, stated: packets are expected in timestamp order (a late packet for a closed window is ingested but that
window is not re-scored); a flow that spans a window boundary is judged on what was seen when the window closed;
a node with no baseline is not scored (cold start); state grows without bound and `flows()` is linear in capture
size, so per-chunk cost grows with capture length (measured in `experiments/streaming_anomaly_benchmark.py`).
Never imports ground truth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

from backend.app.models.anomaly import Anomaly, AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.packet import Packet
from backend.app.models.topology import Node
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
from backend.flowmind.baseline.node_baseline import NodeBehavioralBaseline
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.topology.incremental import IncrementalTopology

# Dimensions whose value can only grow as a window fills, so an upward deviation on partial evidence is already
# real evidence (the final value will be at least as large).
_MONOTONE_UP = frozenset({AnomalyDimension.DESTINATIONS, AnomalyDimension.TRAFFIC_VOLUME})
_NOVELTY = frozenset({AnomalyDimension.PORTS, AnomalyDimension.PROTOCOLS})


@dataclass(frozen=True)
class StreamAlert:
    anomaly: Anomaly
    epoch: int
    partial: bool  # True: raised on an open window; False: raised when the window closed
    raised_wall: float  # time.perf_counter() at the moment the alert was produced


def _trusted_on_partial_window(anomaly: Anomaly) -> bool:
    if anomaly.dimension in _NOVELTY:
        return True
    if anomaly.dimension in _MONOTONE_UP:
        return float(anomaly.evidence_values.get("z_score", "0")) > 0
    return False


class StreamingAnomalyDetector:
    def __init__(
        self,
        capture_id: str,
        baselines: Dict[str, NodeBehavioralBaseline],
        node_ips: Dict[str, str],
        anchor: datetime,
        window_seconds: float,
        scoring_start: datetime,
        z_threshold: float = 3.0,
        record_closed: bool = False,
    ) -> None:
        missing = set(baselines) - set(node_ips)
        if missing:
            raise ValueError(f"baselines without a node IP: {sorted(missing)}")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._topology = IncrementalTopology(capture_id)
        self._baselines = baselines
        self._nodes: Dict[str, Node] = {
            node_id: Node(node_id=node_id, ip_addresses=[node_ips[node_id]], first_observed=anchor, last_observed=anchor)
            for node_id in baselines
        }
        self._node_by_ip: Dict[str, str] = {node_ips[n]: n for n in baselines}
        self._anchor = anchor
        self._window = window_seconds
        self._scoring_start = scoring_start
        self._z = z_threshold
        self._latest: Optional[datetime] = None
        self._epoch: Optional[int] = None
        self._alerted: Set[Tuple[str, AnomalyDimension]] = set()
        self.packet_count = 0
        # {(epoch, node_id): whole-window fingerprint at close}; only kept when asked (equivalence checking).
        self.closed_fingerprints: Optional[Dict[Tuple[int, str], BehavioralFingerprint]] = {} if record_closed else None

    # -- time helpers ---------------------------------------------------------------------------------------------
    def epoch_of(self, ts: datetime) -> int:
        return int((ts - self._anchor).total_seconds() // self._window)

    def epoch_start(self, epoch: int) -> datetime:
        return self._anchor + timedelta(seconds=epoch * self._window)

    def epoch_end(self, epoch: int) -> datetime:
        return self.epoch_start(epoch + 1)

    def _scored(self, epoch: int) -> bool:
        return self.epoch_start(epoch) >= self._scoring_start

    # -- fingerprinting -------------------------------------------------------------------------------------------
    def window_fingerprints(self, epoch: int, node_ids: Sequence[str], computed_at: datetime) -> Dict[str, BehavioralFingerprint]:
        """Fingerprints of `node_ids` over window `epoch` from the flows seen so far (same epoch filter and window
        length the batch path uses)."""
        start, end = self.epoch_start(epoch), self.epoch_end(epoch)
        flows = [f for f in self._topology.flows() if start <= f.last_seen < end]
        windows = {ObservationWindow.SHORT: self._window}
        return {
            n: assemble_node_fingerprint(flows, self._nodes[n], ObservationWindow.SHORT, windows, computed_at=computed_at)
            for n in node_ids
        }

    # -- scoring --------------------------------------------------------------------------------------------------
    def _score(self, epoch: int, node_ids: Sequence[str], computed_at: datetime, partial: bool) -> List[StreamAlert]:
        alerts: List[StreamAlert] = []
        for node_id, fp in self.window_fingerprints(epoch, node_ids, computed_at).items():
            if not partial and self.closed_fingerprints is not None:
                self.closed_fingerprints[(epoch, node_id)] = fp
            for anomaly in detect_node_anomalies(self._baselines[node_id], fp, z_threshold=self._z):
                key = (node_id, anomaly.dimension)
                if key in self._alerted or (partial and not _trusted_on_partial_window(anomaly)):
                    continue
                self._alerted.add(key)
                alerts.append(StreamAlert(anomaly, epoch, partial, time.perf_counter()))
        return alerts

    def close_window(self, epoch: int, computed_at: datetime) -> List[StreamAlert]:
        """Judges every node on the whole of window `epoch` (the batch-equivalent check) and starts a fresh window."""
        alerts = self._score(epoch, sorted(self._nodes), computed_at, partial=False) if self._scored(epoch) else []
        self._alerted = set()
        return alerts

    # -- ingestion ------------------------------------------------------------------------------------------------
    def ingest(self, packets: Sequence[Packet]) -> List[StreamAlert]:
        """Adds `packets` (timestamp order) and returns the alerts they caused. A chunk that crosses a window
        boundary is split there, so the closing window is judged before any packet of the next one is added."""
        alerts: List[StreamAlert] = []
        run: List[Packet] = []
        for pkt in packets:
            epoch = self.epoch_of(pkt.timestamp)
            if self._epoch is not None and epoch > self._epoch:
                alerts.extend(self._ingest_run(run))
                run = []
                alerts.extend(self.close_window(self._epoch, self.epoch_end(self._epoch)))
                self._epoch = epoch
            elif self._epoch is None:
                self._epoch = epoch
            run.append(pkt)
        alerts.extend(self._ingest_run(run))
        return alerts

    def _ingest_run(self, run: List[Packet]) -> List[StreamAlert]:
        if not run:
            return []
        self._topology.ingest(run)
        self.packet_count += len(run)
        newest = max(p.timestamp for p in run)
        self._latest = newest if self._latest is None else max(self._latest, newest)
        if self._epoch is None or not self._scored(self._epoch):
            return []
        touched = sorted(
            {self._node_by_ip[ip] for p in run for ip in (str(p.src_ip), str(p.dst_ip)) if ip in self._node_by_ip}
        )
        return self._score(self._epoch, touched, self._latest, partial=True) if touched else []

    def flush(self) -> List[StreamAlert]:
        """Ends the stream: judges the still-open window as if it had just closed."""
        if self._epoch is None:
            return []
        return self.close_window(self._epoch, self.epoch_end(self._epoch))
