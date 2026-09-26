"""PCAP vs NetFlow v5 / IPFIX ingestion of the same traffic, measured (spec Phase 95).

Path A: pcap -> ingest_pcap -> normalize -> reconstruct -> topology.
Path B: the same pcap -> this project's software exporter -> v5 / IPFIX bytes -> ingest_flow_export -> reconstruct ->
        topology (the unchanged downstream code).
The exporter is our own (no vendor device or real NetFlow capture is available), so this measures the ingestion path
and the information a flow record loses, not a particular device's behaviour.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Sequence, Tuple

from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.l2 import Ether
from scapy.packet import Raw
from scapy.utils import wrpcap

from backend.app.models.packet import Packet, TransportProtocol
from backend.app.models.topology import TopologyGraph
from backend.nettrace.capture.ingest import ingest_flow_export, ingest_pcap
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.flowexport import ipfix, netflow_v5
from backend.nettrace.flowexport.exporter import export_pcap
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import flows_path
from experiments.incremental_topology_benchmark import LEVELS, scenario_packets
from backend.app.models.flow import Flow

SEEDS: Tuple[int, ...] = (42, 43)
FLAG_BITS = {"FIN": 0x01, "SYN": 0x02, "RST": 0x04, "PSH": 0x08, "ACK": 0x10, "URG": 0x20}


def write_pcap(packets: Sequence[Packet], path: Path) -> None:
    """Real Ethernet/IP/TCP|UDP frames whose lengths equal each Packet's size, timestamps preserved."""
    frames = []
    for p in sorted(packets, key=lambda x: x.timestamp):
        l4 = TCP(sport=p.src_port or 0, dport=p.dst_port or 0,
                 flags=sum(FLAG_BITS.get(f, 0) for f in (p.tcp_flags or "").split(","))) \
            if p.protocol == TransportProtocol.TCP else UDP(sport=p.src_port or 0, dport=p.dst_port or 0)
        hdr = 20 + (20 if p.protocol == TransportProtocol.TCP else 8)
        pad = max(p.size_bytes - 14 - hdr, 0)
        frame = Ether() / IP(src=str(p.src_ip), dst=str(p.dst_ip)) / l4 / Raw(b"\0" * pad)
        frame.time = p.timestamp.timestamp()
        frames.append(frame)
    wrpcap(str(path), frames)


def persistent_variant(packets: Sequence[Packet]) -> List[Packet]:
    """Same traffic, but each client<->service pair reuses ONE client port (long-lived connections) and every TCP
    connection carries a handshake (SYN, SYN+ACK, ACK) then ACK/PSH data. The as-generated traffic uses a fresh port
    per packet pair, so every flow record holds a single packet and aggregation is never exercised; this variant does.
    """
    by_pair: Dict[frozenset, Dict[str, set]] = {}
    for p in packets:
        if p.src_port is not None:
            by_pair.setdefault(frozenset({str(p.src_ip), str(p.dst_ip)}), {}).setdefault(str(p.src_ip), set()).add(p.src_port)
    server_port: Dict[frozenset, Tuple[str, int]] = {}
    for pair, ports in by_pair.items():
        ip, pset = min(ports.items(), key=lambda kv: len(kv[1]))
        server_port[pair] = (ip, min(pset))
    out: List[Packet] = []
    seen: Dict[tuple, int] = {}
    for p in sorted(packets, key=lambda x: x.timestamp):
        if p.src_port is None or p.dst_port is None:
            out.append(p)
            continue
        pair = frozenset({str(p.src_ip), str(p.dst_ip)})
        srv_ip, srv_port = server_port[pair]
        client_port = 40000 + sum(map(ord, "".join(sorted(pair)))) % 1000
        sp, dp = (srv_port, client_port) if str(p.src_ip) == srv_ip else (client_port, srv_port)
        key = (pair, p.protocol)
        n = seen[key] = seen.get(key, 0) + 1
        flags = None
        if p.protocol == TransportProtocol.TCP:
            flags = {1: "SYN", 2: "SYN,ACK", 3: "ACK"}.get(n, "ACK,PSH")
        out.append(p.model_copy(update={"src_port": sp, "dst_port": dp, "tcp_flags": flags}))
    return out


def _graph(root: Path, cid: str) -> Tuple[TopologyGraph, List[Flow]]:
    ensure_packets(root, cid)
    flows = reconstruct_flows(root, cid)
    return build_topology_graph(root, cid, graph_id=cid), flows


def _pairs(g: TopologyGraph) -> Dict[frozenset, float]:
    ip = {n.node_id: str(n.ip_addresses[0]) for n in g.nodes}
    return {frozenset({ip[e.source_node_id], ip[e.target_node_id]}): e.confidence for e in g.edges}


def _flow_keys(flows: Sequence[Flow]) -> set:
    return {(str(f.src_ip), str(f.dst_ip), f.src_port, f.dst_port, f.protocol.value) for f in flows}


@dataclass(frozen=True)
class Row:
    variant: str
    level: str
    seed: int
    fmt: str
    nodes_equal: bool
    edges_equal: bool
    edge_f1_vs_pcap: float
    flow_keys_equal: bool
    packets_pcap: int
    packets_export: int
    records: int
    conf_mae: float
    conf_max_diff: float
    mean_conf_pcap: float
    mean_conf_export: float


def compare(level: str, seed: int, fmt: str, work: Path, variant: str = "generated") -> Row:
    pkts = scenario_packets(level, seed)
    if variant == "persistent":
        pkts = persistent_variant(pkts)
    pcap = work / f"{level}-{seed}-{variant}.pcap"
    write_pcap(pkts, pcap)
    root = work / f"root-{level}-{seed}-{fmt}-{variant}"
    ingest_pcap(pcap, root, "cap-a", source="pcap_upload")
    ga, fa = _graph(root, "cap-a")

    records = export_pcap(pcap, ipv4_only=(fmt == "v5"))
    blob = (netflow_v5 if fmt == "v5" else ipfix).encode(records)
    export = work / f"{level}-{seed}-{variant}.{fmt}"
    export.write_bytes(blob)
    manifest = ingest_flow_export(export, root, "cap-b", fmt)
    gb, fb = _graph(root, "cap-b")

    pa, pb = _pairs(ga), _pairs(gb)
    common = set(pa) & set(pb)
    tp = len(common)
    f1 = 2 * tp / (len(pa) + len(pb)) if (pa or pb) else 1.0
    diffs = [abs(pa[k] - pb[k]) for k in common]
    return Row(
        variant, level, seed, fmt,
        {str(n.ip_addresses[0]) for n in ga.nodes} == {str(n.ip_addresses[0]) for n in gb.nodes},
        set(pa) == set(pb), f1, _flow_keys(fa) == _flow_keys(fb),
        len(read_jsonl(root / "captures" / "cap-a" / "packets.jsonl", Packet)), manifest.packet_count, len(records),
        fmean(diffs) if diffs else float("nan"), max(diffs, default=float("nan")),
        fmean(pa.values()) if pa else float("nan"), fmean(pb.values()) if pb else float("nan"),
    )


def run(levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS, formats: Sequence[str] = ("v5", "ipfix"),
        variants: Sequence[str] = ("generated", "persistent")) -> List[Row]:
    work = Path(tempfile.mkdtemp(prefix="flowexport-"))
    try:
        return [compare(l, s, f, work, v) for v in variants for l in levels for s in seeds for f in formats]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def format_rows(rows: Sequence[Row]) -> str:
    head = "variant    level          seed fmt   nodes= edges= F1    flowkeys= pkts(pcap/exp) recs  confMAE confMax mean(pcap/exp)"
    lines = [head]
    for r in rows:
        lines.append(
            f"{r.variant:10s} {r.level:14s} {r.seed:4d} {r.fmt:5s} {str(r.nodes_equal):6s} {str(r.edges_equal):6s} {r.edge_f1_vs_pcap:.3f} "
            f"{str(r.flow_keys_equal):9s} {r.packets_pcap:6d}/{r.packets_export:<6d} {r.records:5d} {r.conf_mae:.4f}  "
            f"{r.conf_max_diff:.4f} {r.mean_conf_pcap:.3f}/{r.mean_conf_export:.3f}"
        )
    return "\n".join(lines)
