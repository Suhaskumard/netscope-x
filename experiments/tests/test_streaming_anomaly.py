"""Phase 86: streaming anomaly detection."""

from __future__ import annotations

import pytest

from backend.app.models.anomaly import AnomalyDimension
from backend.flowmind.anomaly.streaming import StreamingAnomalyDetector
from experiments import streaming_anomaly_benchmark as B


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    return B.build_case(tmp_path_factory.mktemp("strm"), "small", 1.0, 42)


def test_baseline_without_node_ip_is_rejected(case):
    with pytest.raises(ValueError):
        StreamingAnomalyDetector("c", case.baselines, {}, B.BASE_TIME, 60.0, B.BASE_TIME)


def test_history_windows_are_never_scored(case):
    det = B.make_detector(case)
    history = [p for p in case.packets if p.timestamp < det._scoring_start]
    alerts = []
    for chunk in B.chunks(history, 10):
        alerts.extend(det.ingest(chunk))
    assert alerts == []


def test_each_node_dimension_alerts_once_per_window(case):
    _, alerts = B.run_stream(case)
    keys = [(a.epoch, a.anomaly.node_id, a.anomaly.dimension) for a in alerts]
    assert len(keys) == len(set(keys))


def test_partial_alerts_are_only_trusted_dimensions(case):
    _, alerts = B.run_stream(case)
    for a in alerts:
        if a.partial and a.anomaly.dimension in (AnomalyDimension.DESTINATIONS, AnomalyDimension.TRAFFIC_VOLUME):
            assert float(a.anomaly.evidence_values["z_score"]) > 0
        if a.partial:
            assert a.anomaly.dimension not in (AnomalyDimension.TIMING, AnomalyDimension.BEHAVIOR)


def test_result_is_independent_of_chunking(case):
    def keyset(size):
        _, alerts = B.run_stream(case, chunk_size=size)
        return {(a.epoch, a.anomaly.node_id, a.anomaly.dimension) for a in alerts if not a.partial}

    assert keyset(1) == keyset(25) == keyset(10_000)


def test_closed_windows_match_batch_fingerprints_and_alerts(case):
    row = B.score_case(case)
    assert row is not None
    assert row.fingerprints_equal + row.mismatches_explained == row.fingerprints_total
    assert row.alert_sets_equal


def test_streaming_detects_earlier_than_batch_epoch_boundary(case):
    row = B.score_case(case)
    assert row.stream_recall == row.batch_recall == 1.0
    assert row.stream_latency < row.batch_latency


def test_load_row_reports_real_measurements(case):
    row = B.run_load(case, rate=1000.0)
    assert row.packets == len(case.packets) and row.chunk_ms_max >= row.chunk_ms_p50 > 0
    assert row.alerts_on_labels > 0 and row.latency_p50 is not None and row.latency_p50 > 0
    # a rate far above what the detector can process must show a backlog rather than a fabricated low latency
    assert B.run_load(case, rate=1e9).final_backlog_seconds > row.final_backlog_seconds
