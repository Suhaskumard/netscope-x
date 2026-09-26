"""Phase 103: the real-trace harness, exercised on pcaps WRITTEN BY THIS TEST with Scapy. They are small real-format captures of a
known exchange, not real-world data; they prove the accounting and proxy metrics are computed correctly, not how the pipeline does
on external traces (that stays NOT RUN until the user supplies pcaps)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from scapy.all import ARP, IP, IPv6, TCP, Ether, wrpcap

import experiments.real_trace_validation as rtv


ETH = Ether(src="00:00:00:00:00:01", dst="00:00:00:00:00:02")  # explicit MACs: no neighbor resolution


def _tcp(src, dst, sport, dport, t, flags="PA"):
    p = ETH / IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags=flags) / (b"x" * 20)
    p.time = t
    return p


def _write_trace(path: Path) -> dict:
    pkts, t = [], 1_700_000_000.0
    for client, sport in (("10.0.0.1", 40001), ("10.0.0.4", 40002)):
        for _ in range(6):
            pkts += [_tcp(client, "10.0.0.2", sport, 443, t), _tcp("10.0.0.2", client, 443, sport, t + 0.01)]
            t += 1.0
    for _ in range(6):
        pkts += [_tcp("10.0.0.1", "10.0.0.3", 40003, 5432, t), _tcp("10.0.0.3", "10.0.0.1", 5432, 40003, t + 0.01)]
        t += 1.0
    arp = ETH / ARP()
    arp.time = t
    v6 = ETH / IPv6(src="fe80::1", dst="fe80::2") / TCP(sport=1234, dport=443) / b"y"
    v6.time = t + 1
    pkts += [arp, v6]
    wrpcap(str(path), pkts)
    return {"frames": len(pkts), "ip_frames": len(pkts) - 1}


@pytest.fixture()
def traces(tmp_path):
    d = tmp_path / "traces"
    d.mkdir()
    expected = _write_trace(d / "known.pcap")
    return d, expected


def test_accounting_matches_independent_count(traces, tmp_path):
    d, expected = traces
    r = rtv.validate_trace(d / "known.pcap", tmp_path / "root", 0, 1, rtv.DEFAULT_MAX_BYTES, None)
    assert r["status"] == "OK"
    a = r["accounting"]
    assert (a["frames"], a["ip_frames"], a["non_ip_skipped"]) == (expected["frames"], expected["ip_frames"], 1)
    assert a["unexplained_drops"] == 0 and a["packets_normalized"] == expected["ip_frames"]
    assert a["nodes"] >= 4 and a["edges"] >= 3


def test_edge_recovery_and_roles(traces, tmp_path):
    d, _ = traces
    r = rtv.validate_trace(d / "known.pcap", tmp_path / "root", 0, 1, rtv.DEFAULT_MAX_BYTES, None)
    assert r["edge_recovery"]["edges_without_supporting_flow"] == 0
    ra = r["role_agreement"]
    # servers: 10.0.0.2 and fe80::2 on 443 (API), 10.0.0.3 on 5432; clients: 10.0.0.1, 10.0.0.4, fe80::1
    assert ra["label_distribution"] == {"API": 2, "Database": 1, "Client": 3}
    assert "majority_class_baseline" in ra or ra["status"] != "ok"


def test_stability_full_is_identical_and_deterministic(traces, tmp_path):
    d, _ = traces
    a = rtv.validate_trace(d / "known.pcap", tmp_path / "r1", 0, 5, rtv.DEFAULT_MAX_BYTES, None)["stability"]
    b = rtv.validate_trace(d / "known.pcap", tmp_path / "r2", 0, 5, rtv.DEFAULT_MAX_BYTES, None)["stability"]
    assert a == b
    assert a[0]["completeness"] == 1.0 and a[0]["edge_jaccard"] == 1.0 and a[0]["node_retention"] == 1.0
    assert all(0.0 <= r["edge_jaccard"] <= 1.0 for r in a)


def test_labeled_edge_scores(traces, tmp_path):
    d, _ = traces
    labels = {"known.pcap": {"edges": [["10.0.0.1", "10.0.0.2"], ["10.0.0.4", "10.0.0.2"], ["10.0.0.1", "10.0.0.3"], ["10.0.0.9", "10.0.0.8"]]}}
    r = rtv.validate_trace(d / "known.pcap", tmp_path / "root", 0, 1, rtv.DEFAULT_MAX_BYTES, labels)
    s = r["labeled_edge_scores"]
    assert s["edge_recall"] == pytest.approx(0.75) and 0 < s["edge_precision"] <= 1


def test_corrupt_and_oversize_are_reported_not_skipped(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "bad.pcap").write_bytes(b"not a pcap at all")
    _write_trace(d / "big.pcap")
    bad = rtv.validate_trace(d / "bad.pcap", tmp_path / "root", 0, 1, rtv.DEFAULT_MAX_BYTES, None)
    assert bad["status"] == "FAILED" and bad["error"] == "InvalidPcapError"
    big = rtv.validate_trace(d / "big.pcap", tmp_path / "root", 1, 1, 10, None)
    assert big["status"] == "REFUSED"


def test_no_traces_is_not_run_and_writes_no_numbers(tmp_path):
    rep = rtv.run_validation(tmp_path / "missing", tmp_path / "root")
    assert rep["status"] == "NOT_RUN" and "traces" not in rep and "comparison" not in rep
    assert "NOT RUN" in (tmp_path / "root" / "real_trace_validation" / "report.md").read_text(encoding="utf-8")


def test_full_run_compares_against_synthetic(traces, tmp_path):
    d, _ = traces
    rep = rtv.run_validation(d, tmp_path / "root", seed=3)
    assert rep["status"] == "OK" and rep["caveat"] and len(rep["comparison"]) == len(rtv.COMPLETENESS_LEVELS)
    assert rep["comparison"][0]["synthetic_edge_jaccard"] == 1.0 and rep["comparison"][0]["real_edge_jaccard"] == 1.0
    json.loads((tmp_path / "root" / "real_trace_validation" / "report.json").read_text(encoding="utf-8"))
    md = (tmp_path / "root" / "real_trace_validation" / "report.md").read_text(encoding="utf-8")
    assert "proxy" in md and "Real vs synthetic" in md


def test_module_does_not_import_ground_truth():
    tree = ast.parse(Path(rtv.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        assert not any("ground_truth" in n for n in names)
