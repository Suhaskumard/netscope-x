"""Streaming vs batch anomaly detection, and real detection latency under load (spec Phase 86).

Same labeled data as the batch detector's scoring in the Phase 68 matrix (`experiments/anomaly_injection.py`, every
label derived by construction from the injected packets, never from what a detector fires). Three measurements:

  quality      precision/recall/F1 and detection latency (STREAM time: alert time minus injected onset) of
               `StreamingAnomalyDetector` vs the batch epoch-boundary scorer, on the same sampled packets.
  equivalence  at every window close the streaming whole-window fingerprint of every node equals the batch one
               (features compared exactly, `computed_at` excluded), and the set of (node, dimension, epoch) alerts is
               compared with the batch set. Streaming-only alerts (raised on partial evidence and not confirmed by
               the batch window) and batch-only alerts are counted, never hidden.
  load         real per-chunk processing time, and end-to-end wall latency (offer time of the onset packet -> alert)
               at increasing offered rates. Arrivals follow a virtual clock (packet i is offered at i / rate); each
               chunk starts when it is complete AND the previous chunk is done, and takes its REAL measured
               `perf_counter` processing time, so queueing under overload is real but nothing sleeps. Chunk assembly
               time (chunk_size / rate) is part of the latency.

Ground truth is used only for labels here (never by the detector).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.anomaly import Anomaly
from backend.app.models.packet import Packet
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
from backend.flowmind.anomaly.streaming import StreamAlert, StreamingAnomalyDetector
from backend.flowmind.baseline.node_baseline import NodeBehavioralBaseline, build_node_baseline
from backend.nettrace.topology.discovery import discover_nodes
from experiments.anomaly_fingerprints import anomaly_capture_id, fingerprints_from_flows, write_anomaly_capture
from experiments.anomaly_injection import AnomalyDataset, generate_anomaly_dataset
from experiments.matrix_runner import TOPOLOGY_LEVELS, _DETECTOR_DIMENSION_COUNT, _name_to_node_id
from experiments.metrics.anomaly_evaluation import LabeledAnomalyEvent, evaluate_anomaly_detection
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import BASE_TIME, assign_ips

LEVELS: Tuple[str, ...] = ("small", "medium", "large", "multi_path", "multi_service", "dynamic")
COMPLETENESS: Tuple[float, ...] = (1.0, 0.5, 0.25)
SEEDS: Tuple[int, ...] = (42, 43, 44)
CAPTURE = "strm"
CHUNK_SIZE = 25
LOAD_LEVELS: Tuple[str, ...] = ("small", "large")
LOAD_RATES: Tuple[float, ...] = (200.0, 1000.0, 5000.0, 20000.0, 100000.0)


@dataclass
class Case:
    level: str
    completeness: float
    seed: int
    dataset: AnomalyDataset
    packets: List[Packet]  # sampled, timestamp order: exactly what both detectors see
    nodes: list
    node_ips: Dict[str, str]
    baselines: Dict[str, NodeBehavioralBaseline]
    batch_fingerprints: dict
    batch_flows: list
    batch_anomalies: List[Anomaly]
    labels: List[LabeledAnomalyEvent]
    total_checks: int


def build_case(root: Path, level: str, completeness: float, seed: int, packets_per_edge: int = 15) -> Case:
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    dataset = generate_anomaly_dataset(roles, edges, ip_by_name, CAPTURE, seed, packets_per_edge=packets_per_edge)
    packets = sample_packets(dataset.packets, completeness, seed)

    flows = write_anomaly_capture(root, CAPTURE, dataset, completeness, seed)  # the batch path, through disk
    nodes = discover_nodes(root, anomaly_capture_id(CAPTURE))
    fingerprints = fingerprints_from_flows(flows, dataset, nodes)

    first_test = dataset.baseline_epochs
    baselines = {n.node_id: build_node_baseline(fingerprints[n.node_id][:first_test]) for n in nodes}
    batch_anomalies: List[Anomaly] = []
    for node in nodes:
        for fp in fingerprints[node.node_id][first_test:]:
            batch_anomalies.extend(detect_node_anomalies(baselines[node.node_id], fp))

    name_to_node_id = _name_to_node_id(nodes, ip_by_name)
    labels = [
        LabeledAnomalyEvent(node_id=name_to_node_id[name], dimension=dim, onset_at=inj.onset_at)
        for inj in dataset.injected
        for name, dim in inj.labels
        if name in name_to_node_id
    ]
    return Case(
        level, completeness, seed, dataset, packets, nodes,
        {n.node_id: str(n.ip_addresses[0]) for n in nodes}, baselines, fingerprints, flows, batch_anomalies, labels,
        total_checks=len(nodes) * _DETECTOR_DIMENSION_COUNT * dataset.test_epochs,
    )


def make_detector(case: Case, record_closed: bool = False) -> StreamingAnomalyDetector:
    d = case.dataset
    return StreamingAnomalyDetector(
        CAPTURE + "-anomaly", case.baselines, case.node_ips, anchor=BASE_TIME, window_seconds=d.epoch_seconds,
        scoring_start=d.epoch_start(d.baseline_epochs), record_closed=record_closed,
    )


def chunks(packets: Sequence[Packet], size: int):
    for i in range(0, len(packets), size):
        yield packets[i:i + size]


def run_stream(case: Case, chunk_size: int = CHUNK_SIZE, record_closed: bool = False):
    det = make_detector(case, record_closed)
    alerts: List[StreamAlert] = []
    for chunk in chunks(case.packets, chunk_size):
        alerts.extend(det.ingest(chunk))
    alerts.extend(det.flush())
    return det, alerts


@dataclass(frozen=True)
class QualityRow:
    level: str
    completeness: float
    seed: int
    labels: int
    stream_f1: float
    batch_f1: float
    stream_recall: float
    batch_recall: float
    stream_fp: int
    batch_fp: int
    stream_latency: Optional[float]
    batch_latency: Optional[float]
    partial_alerts: int
    close_alerts: int
    fingerprints_equal: int
    fingerprints_total: int
    mismatches_explained: int  # mismatches where a batch flow starts in the window but ends in a later one
    alert_sets_equal: bool
    stream_only: int  # raised on partial evidence, not present in the batch set
    batch_only: int


def _alert_key(node_id: str, dimension, epoch: int) -> Tuple[str, str, int]:
    return (node_id, dimension.value, epoch)


def score_case(case: Case, chunk_size: int = CHUNK_SIZE) -> Optional[QualityRow]:
    if not case.labels:
        return None
    det, alerts = run_stream(case, chunk_size, record_closed=True)
    stream_eval = evaluate_anomaly_detection([a.anomaly for a in alerts], case.labels, case.total_checks)
    batch_eval = evaluate_anomaly_detection(case.batch_anomalies, case.labels, case.total_checks)

    d = case.dataset
    equal = total = explained = 0
    for (epoch, node_id), fp in det.closed_fingerprints.items():
        ref = case.batch_fingerprints[node_id][epoch]
        total += 1
        if fp.model_dump(exclude={"computed_at"}) == ref.model_dump(exclude={"computed_at"}):
            equal += 1
            continue
        # The batch window keeps a flow by its LAST packet, so a five-tuple that recurs in a later window drops out
        # of the earlier one there; the stream had only seen the earlier part. Check that this is what happened.
        ip, start, end = case.node_ips[node_id], det.epoch_start(epoch), det.epoch_end(epoch)
        explained += any(
            ip in (str(f.src_ip), str(f.dst_ip)) and start <= f.first_seen < end <= f.last_seen for f in case.batch_flows
        )

    stream_set = {_alert_key(a.anomaly.node_id, a.anomaly.dimension, a.epoch) for a in alerts}
    batch_set = {
        _alert_key(a.node_id, a.dimension, int((a.detected_at - BASE_TIME).total_seconds() // d.epoch_seconds) - 1)
        for a in case.batch_anomalies
    }
    return QualityRow(
        case.level, case.completeness, case.seed, len(case.labels),
        stream_eval.f1, batch_eval.f1, stream_eval.recall, batch_eval.recall,
        stream_eval.false_positive_count, batch_eval.false_positive_count,
        stream_eval.mean_detection_latency_seconds, batch_eval.mean_detection_latency_seconds,
        sum(a.partial for a in alerts), sum(not a.partial for a in alerts),
        equal, total, explained, stream_set == batch_set, len(stream_set - batch_set), len(batch_set - stream_set),
    )


def run_quality(root: Path, levels=LEVELS, seeds=SEEDS, completeness=COMPLETENESS) -> List[QualityRow]:
    rows: List[QualityRow] = []
    for level in levels:
        for c in completeness:
            for seed in seeds:
                row = score_case(build_case(root, level, c, seed))
                if row is not None:
                    rows.append(row)
    return rows


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    real = [v for v in values if v is not None]
    return fmean(real) if real else None


def _fmt(v: Optional[float], spec: str = ".3f") -> str:
    return "n/a" if v is None else format(v, spec)


def format_quality(rows: Sequence[QualityRow]) -> str:
    lines = [
        "quality: streaming vs batch (means over cells; latency = stream seconds from injected onset to alert)",
        f"{'level':<14}{'cells':>6}{'F1 str':>8}{'F1 bat':>8}{'rec str':>9}{'rec bat':>9}{'FP str':>8}{'FP bat':>8}"
        f"{'lat str':>9}{'lat bat':>9}{'fp==':>10}{'sets==':>8}{'str-only':>9}{'bat-only':>9}",
    ]
    for level in dict.fromkeys(r.level for r in rows):
        rs = [r for r in rows if r.level == level]
        lines.append(
            f"{level:<14}{len(rs):>6}{_fmt(_mean([r.stream_f1 for r in rs]), '.3f'):>8}"
            f"{_fmt(_mean([r.batch_f1 for r in rs]), '.3f'):>8}{_fmt(_mean([r.stream_recall for r in rs]), '.3f'):>9}"
            f"{_fmt(_mean([r.batch_recall for r in rs]), '.3f'):>9}{sum(r.stream_fp for r in rs):>8}"
            f"{sum(r.batch_fp for r in rs):>8}{_fmt(_mean([r.stream_latency for r in rs]), '.1f'):>9}"
            f"{_fmt(_mean([r.batch_latency for r in rs]), '.1f'):>9}"
            + f"{sum(r.fingerprints_equal for r in rs)}/{sum(r.fingerprints_total for r in rs)}".rjust(10)
            + f"{sum(r.alert_sets_equal for r in rs)}/{len(rs)}".rjust(8)
            + f"{sum(r.stream_only for r in rs):>9}{sum(r.batch_only for r in rs):>9}"
        )
    n = len(rows)
    lines.append(
        f"ALL {n} cells: fingerprints equal {sum(r.fingerprints_equal for r in rows)}/{sum(r.fingerprints_total for r in rows)} "
        f"(mismatches explained by a flow recurring in a later window: {sum(r.mismatches_explained for r in rows)}); "
        f"alert sets identical {sum(r.alert_sets_equal for r in rows)}/{n}; "
        f"partial-window alerts {sum(r.partial_alerts for r in rows)}, close-time alerts {sum(r.close_alerts for r in rows)}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- load
@dataclass(frozen=True)
class LoadRow:
    level: str
    rate: float
    packets: int
    chunk_size: int
    chunk_ms_p50: float
    chunk_ms_p95: float
    chunk_ms_max: float
    alerts_on_labels: int
    latency_p50: Optional[float]  # wall seconds, offer of onset packet -> alert, alerts matching a label
    latency_max: Optional[float]
    final_backlog_seconds: float  # how far behind real time the detector finished (0 = kept up)


def _pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def run_load(case: Case, rate: float, chunk_size: int = CHUNK_SIZE) -> LoadRow:
    det = make_detector(case)
    label_keys = {(lab.node_id, lab.dimension) for lab in case.labels}
    onset_index: Dict[datetime, int] = {}
    for i, p in enumerate(case.packets):
        for onset in {lab.onset_at for lab in case.labels}:
            if onset not in onset_index and p.timestamp >= onset:
                onset_index[onset] = i
    onset_of = {(lab.node_id, lab.dimension): lab.onset_at for lab in case.labels}

    durations: List[float] = []
    latencies: List[float] = []
    done = 0.0
    n = len(case.packets)
    for start in range(0, n, chunk_size):
        chunk = case.packets[start:start + chunk_size]
        ready = (start + len(chunk)) / rate  # offer time of the chunk's last packet
        begin = max(ready, done)
        t0 = time.perf_counter()
        alerts = det.ingest(chunk)
        elapsed = time.perf_counter() - t0
        durations.append(elapsed * 1000)
        for a in alerts:
            key = (a.anomaly.node_id, a.anomaly.dimension)
            if key in label_keys and a.anomaly.detected_at >= onset_of[key]:
                raised = begin + (a.raised_wall - t0)
                latencies.append(raised - onset_index[onset_of[key]] / rate)
        done = begin + elapsed
    t0 = time.perf_counter()
    tail = det.flush()  # window-close alerts at end of stream
    end_elapsed = time.perf_counter() - t0
    begin = max(n / rate, done)
    for a in tail:
        key = (a.anomaly.node_id, a.anomaly.dimension)
        if key in label_keys and a.anomaly.detected_at >= onset_of[key]:
            latencies.append(begin + (a.raised_wall - t0) - onset_index[onset_of[key]] / rate)
    done = begin + end_elapsed
    return LoadRow(
        case.level, rate, n, chunk_size, _pct(durations, 0.5), _pct(durations, 0.95), max(durations), len(latencies),
        _pct(latencies, 0.5) if latencies else None, max(latencies) if latencies else None,
        max(0.0, done - n / rate),
    )


def run_load_sweep(root: Path, levels=LOAD_LEVELS, rates=LOAD_RATES, seed: int = 42, chunk_size: int = CHUNK_SIZE):
    rows: List[LoadRow] = []
    for level in levels:
        case = build_case(root, level, 1.0, seed)
        for rate in rates:
            rows.append(run_load(case, rate, chunk_size))
    return rows


def format_load(rows: Sequence[LoadRow]) -> str:
    lines = [
        "load: real processing time, virtual arrival clock (see module docstring); latency = onset packet offered -> alert",
        f"{'level':<8}{'pkts':>7}{'rate pps':>10}{'chunk':>6}{'ms p50':>9}{'ms p95':>9}{'ms max':>9}"
        f"{'labeled':>8}{'lat p50 s':>11}{'lat max s':>11}{'backlog s':>10}",
    ]
    for r in rows:
        lines.append(
            f"{r.level:<8}{r.packets:>7}{r.rate:>10.0f}{r.chunk_size:>6}{r.chunk_ms_p50:>9.2f}{r.chunk_ms_p95:>9.2f}"
            f"{r.chunk_ms_max:>9.2f}{r.alerts_on_labels:>8}{_fmt(r.latency_p50):>11}{_fmt(r.latency_max):>11}"
            f"{r.final_backlog_seconds:>10.3f}"
        )
    return "\n".join(lines)


def scratch_root(root: Path) -> Path:
    path = Path(tempfile.mkdtemp(prefix="streaming_scratch_", dir=root)) if root.exists() else Path(tempfile.mkdtemp())
    return path


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
