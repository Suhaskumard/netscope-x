"""Seeds a real capture with dependencies whose temporal-precedence signal is non-zero (Phase 99 demo/verification).

    python -m scripts.seed_attribution_demo --root <artifact_root>

Takes the Phase 70 `parent_driven_traffic` generator (a child's activity follows its parents' one bucket later) over a matrix
topology, writes it as a real pcap, ingests it through the real capture path, and prints the capture id.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from scapy.all import ICMP, IP, TCP, UDP, wrpcap

from backend.app.models.packet import TransportProtocol
from backend.nettrace.capture.ingest import ingest_pcap
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.streaming_dependency_benchmark import lagged_packets


def write_pcap(packets, path: Path) -> None:
    out = []
    for p in sorted(packets, key=lambda p: p.timestamp):
        ip = IP(src=str(p.src_ip), dst=str(p.dst_ip))
        if p.protocol == TransportProtocol.UDP:
            pkt = ip / UDP(sport=p.src_port or 0, dport=p.dst_port or 0) / (b"x" * max(0, p.size_bytes - 28))
        elif p.protocol == TransportProtocol.TCP:
            pkt = ip / TCP(sport=p.src_port or 0, dport=p.dst_port or 0, flags="PA") / (b"x" * max(0, p.size_bytes - 40))
        else:
            pkt = ip / ICMP()
        pkt.time = p.timestamp.timestamp()
        out.append(pkt)
    wrpcap(str(path), out)


def seed(root: Path, level: str = "large", seed_value: int = 42) -> dict:
    capture_id = uuid.uuid4().hex
    packets = lagged_packets(level, seed_value)
    with tempfile.TemporaryDirectory() as tmp:
        pcap = Path(tmp) / "attr.pcap"
        write_pcap(packets, pcap)
        ingest_pcap(pcap, root, capture_id, original_filename="attr.pcap")
    ensure_packets(root, capture_id)
    reconstruct_flows(root, capture_id)
    return {"capture_id": capture_id, "packets": len(packets), "topology": level}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--level", default="large")
    args = parser.parse_args()
    print(json.dumps(seed(args.root, args.level)))
