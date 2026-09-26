"""Phase 95: NetFlow v5 / IPFIX ingestion as an alternate capture source."""

from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient
from scapy.layers.netflow import NetflowHeader, NetflowHeaderV5, NetflowRecordV5

from backend.app.auth.store import CredentialStore
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.tenancy.paths import tenant_inbox
from backend.app.tenancy.store import TenantRegistry
from backend.nettrace.flowexport import decode, ipfix, netflow_v5, records_to_packets
from backend.nettrace.flowexport.records import FlowExportError, FlowRecord
from experiments import flow_export_benchmark as B

client = TestClient(app)

R4 = FlowRecord("10.0.0.1", "10.0.0.2", 1234, 80, 6, 5, 700, 1000.5, 1002.25, 0x1B)
R4b = FlowRecord("10.0.0.2", "10.0.0.1", 80, 1234, 6, 4, 900, 1000.75, 1002.5, 0x1A)
R6 = FlowRecord("2001:db8::1", "2001:db8::2", 5000, 443, 17, 3, 300, 2000.0, 2001.0, 0)


def test_v5_roundtrip_and_scapy_agrees() -> None:
    blob = netflow_v5.encode([R4, R4b], export_time=1010.0)
    assert netflow_v5.decode(blob) == [R4, R4b]
    parsed = NetflowHeader(blob)  # Scapy's independent decoder reads what we encoded
    assert parsed.version == 5 and parsed[NetflowHeaderV5].count == 2
    rec = parsed[NetflowRecordV5]
    assert (rec.src, rec.dst, rec.srcport, rec.dstport, rec.prot, rec.dpkts, rec.dOctets) == (
        "10.0.0.1", "10.0.0.2", 1234, 80, 6, 5, 700)
    assert rec.tcpFlags == "FSPA" and rec.last - rec.first == 1750  # ms


def test_v5_many_records_span_datagrams() -> None:
    recs = [FlowRecord("10.0.0.1", "10.0.0.2", 1000 + i, 80, 6, 1, 60, 100.0 + i, 100.0 + i) for i in range(75)]
    assert netflow_v5.decode(netflow_v5.encode(recs)) == recs


def test_ipfix_roundtrip_ipv4_and_ipv6() -> None:
    recs = [R4, R6, R4b]
    got = ipfix.decode(ipfix.encode(recs, per_message=2))
    assert sorted(got, key=lambda r: r.start) == sorted(recs, key=lambda r: r.start)


def test_ipfix_skips_unknown_elements_and_honours_reduced_size() -> None:
    # hand-built message: template with an unknown IE (id 999, 3 bytes) and 4-byte packet/octet counters
    fields = [(8, 4), (12, 4), (7, 2), (11, 2), (4, 1), (999, 3), (2, 4), (1, 4), (152, 8), (153, 8)]
    tmpl = struct.pack("!HH", 300, len(fields)) + b"".join(struct.pack("!HH", i, n) for i, n in fields)
    tset = struct.pack("!HH", 2, 4 + len(tmpl)) + tmpl
    rec = (bytes([10, 0, 0, 1]) + bytes([10, 0, 0, 2]) + struct.pack("!HHB", 1, 2, 6) + b"xyz"
           + struct.pack("!II", 7, 900) + struct.pack("!QQ", 5000, 6000))
    dset = struct.pack("!HH", 300, 4 + len(rec)) + rec
    body = tset + dset
    msg = struct.pack("!HHIII", 10, 16 + len(body), 0, 0, 7) + body
    (r,) = ipfix.decode(msg)
    assert (r.packets, r.octets, r.start, r.end, r.protocol) == (7, 900, 5.0, 6.0, 6)


@pytest.mark.parametrize("fmt", ["v5", "ipfix"])
def test_malformed_exports_are_rejected_not_crashing(fmt) -> None:
    good = (netflow_v5 if fmt == "v5" else ipfix).encode([R4, R4b])
    bad = [b"", b"\x00" * 10, good[:-5], good[:10], b"garbage" * 20, bytes([0, 9]) + good[2:]]
    for blob in bad:
        with pytest.raises(FlowExportError):
            decode(blob, fmt)


def test_ipfix_data_set_without_template_and_variable_length_rejected() -> None:
    no_template = struct.pack("!HHIII", 10, 16 + 8, 0, 0, 1) + struct.pack("!HH", 256, 8) + b"\0\0\0\0"
    with pytest.raises(FlowExportError):
        ipfix.decode(no_template)
    tmpl = struct.pack("!HH", 300, 1) + struct.pack("!HH", 8, 0xFFFF)
    body = struct.pack("!HH", 2, 4 + len(tmpl)) + tmpl
    with pytest.raises(FlowExportError):
        ipfix.decode(struct.pack("!HHIII", 10, 16 + len(body), 0, 0, 1) + body)
    with pytest.raises(FlowExportError):
        decode(b"x", "netflow9")


def test_v5_cannot_encode_ipv6() -> None:
    with pytest.raises(FlowExportError):
        netflow_v5.encode([R6])


def test_record_expansion_preserves_counts_and_bytes() -> None:
    pkts = records_to_packets([R4, R6], "c")
    assert len(pkts) == 8 and sum(p.size_bytes for p in pkts) == 1000
    assert all(p.tcp_flags is None for p in pkts)
    assert [p.packet_id for p in pkts] == [f"c:{i}" for i in range(8)]
    assert pkts == sorted(pkts, key=lambda p: p.timestamp)


# ---- the spec's verification: same traffic through pcap vs flow export, same downstream pipeline ----
@pytest.mark.parametrize("variant", ["generated", "persistent"])
@pytest.mark.parametrize("fmt", ["v5", "ipfix"])
def test_flow_export_and_pcap_give_same_topology(tmp_path, fmt, variant) -> None:
    row = B.compare("small", 42, fmt, tmp_path, variant)
    assert row.nodes_equal and row.edges_equal and row.flow_keys_equal
    assert row.edge_f1_vs_pcap == 1.0
    assert row.packets_pcap == row.packets_export
    assert row.conf_max_diff < 0.05
    if variant == "persistent":
        assert row.records < row.packets_pcap / 5  # aggregation really happened


def test_handshake_evidence_is_lost_in_flow_records(tmp_path) -> None:
    """Measured limitation: a record carries only OR'd flags, so confidence can fall vs the pcap path."""
    row = B.compare("large", 42, "ipfix", tmp_path, "persistent")
    assert row.edges_equal and row.mean_conf_export <= row.mean_conf_pcap


# ---- API end to end, with tenancy and auth on ----
@pytest.fixture()
def secured(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_TENANCY_ENABLED", "true")
    monkeypatch.setenv("NETSCOPE_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    TenantRegistry(root).create_tenant("alpha")
    TenantRegistry(root).create_tenant("beta")
    store = CredentialStore(root)
    yield root, {t: {"Authorization": f"Bearer {store.create(t, 'operator', tenant_id=t)}"} for t in ("alpha", "beta")}
    get_settings.cache_clear()


def test_api_netflow_upload_end_to_end(secured) -> None:
    root, h = secured
    (tenant_inbox(root, "alpha") / "x.ipfix").write_bytes(ipfix.encode([R4, R4b]))
    (tenant_inbox(root, "alpha") / "x.bad").write_bytes(b"not a flow export")
    ok = client.post("/api/v1/capture", headers=h["alpha"],
                     json={"source": "netflow_upload", "flow_filename": "x.ipfix", "flow_format": "ipfix"})
    assert ok.status_code == 202 and ok.json()["packet_count"] == 9
    cid = ok.json()["capture_id"]
    topo = client.get(f"/api/v1/topology?capture_id={cid}", headers=h["alpha"])
    assert topo.status_code == 200 and len(topo.json()["nodes"]) == 2 and len(topo.json()["edges"]) == 1
    assert client.get(f"/api/v1/flows?capture_id={cid}", headers=h["alpha"]).json()["total"] >= 1
    assert client.get(f"/api/v1/topology?capture_id={cid}", headers=h["beta"]).status_code == 404  # tenant isolation

    bad = client.post("/api/v1/capture", headers=h["alpha"],
                      json={"source": "netflow_upload", "flow_filename": "x.bad", "flow_format": "v5"})
    assert bad.status_code == 422
    for body in ({"source": "netflow_upload"}, {"source": "netflow_upload", "flow_filename": "../x", "flow_format": "v5"},
                 {"source": "netflow_upload", "flow_filename": "nope.v5", "flow_format": "v9"}):
        assert client.post("/api/v1/capture", headers=h["alpha"], json=body).status_code == 422
    missing = client.post("/api/v1/capture", headers=h["alpha"],
                          json={"source": "netflow_upload", "flow_filename": "nope.v5", "flow_format": "v5"})
    assert missing.status_code == 422
