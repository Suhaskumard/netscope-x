"""Seeds a real, multi-snapshot capture for the Phase 97 time-travel explorer.

    python -m scripts.seed_time_travel_demo --root <artifact_root>

Writes a real pcap in which hosts and links appear over time (and one link gets busier), ingests it through the real
capture path, normalizes it, and records four snapshots at increasing `captured_at` with the real `create_snapshot`.
Prints (JSON) the capture id and, per snapshot, the node IPs / edge pairs / confidences read back from the persisted
graph files themselves - the reference values the browser check compares the rendered page against.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scapy.all import IP, TCP, wrpcap

from backend.archaeology.snapshots import create_snapshot, list_snapshots, read_snapshot_graph
from backend.nettrace.capture.ingest import ingest_pcap
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
# (start offset s, src, dst, exchanges): when each link first talks, plus a late burst on A-B
PLAN = [
    (0, "10.0.0.1", "10.0.0.2", 3),
    (100, "10.0.0.2", "10.0.0.3", 3),
    (200, "10.0.0.3", "10.0.0.4", 3),
    (205, "10.0.0.4", "10.0.0.5", 3),
    (300, "10.0.0.1", "10.0.0.2", 40),
]
SNAPSHOT_OFFSETS = [50, 150, 250, 350]


def build_pcap(path: Path) -> None:
    packets = []
    for start, a, b, n in PLAN:
        for i in range(n):
            t = T0.timestamp() + start + i * 0.5
            for src, dst, sp, dp in ((a, b, 41000 + start % 1000, 80), (b, a, 80, 41000 + start % 1000)):
                p = IP(src=src, dst=dst) / TCP(sport=sp, dport=dp, flags="PA")
                p.time = t + (0.01 if src == b else 0.0)
                packets.append(p)
    packets.sort(key=lambda p: float(p.time))
    wrpcap(str(path), packets)


def seed(root: Path) -> dict:
    capture_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as tmp:
        pcap = Path(tmp) / "demo.pcap"
        build_pcap(pcap)
        ingest_pcap(pcap, root, capture_id, original_filename="demo.pcap")
    ensure_packets(root, capture_id)
    reconstruct_flows(root, capture_id)
    for off in SNAPSHOT_OFFSETS:
        create_snapshot(root, capture_id, captured_at=T0 + timedelta(seconds=off))
    expected = []
    for snap in list_snapshots(root, capture_id):
        g = read_snapshot_graph(root, capture_id, snap)
        ip = {n.node_id: str(n.ip_addresses[0]) for n in g.nodes}
        expected.append({
            "version": snap.version, "captured_at": snap.captured_at.isoformat(),
            "nodes": sorted(ip.values()),
            "edges": sorted(f"{min(ip[e.source_node_id], ip[e.target_node_id])}-{max(ip[e.source_node_id], ip[e.target_node_id])}"
                            for e in g.edges),
            "confidence": {f"{min(ip[e.source_node_id], ip[e.target_node_id])}-{max(ip[e.source_node_id], ip[e.target_node_id])}":
                           round(e.confidence, 4) for e in g.edges},
        })
    return {"capture_id": capture_id, "snapshots": expected}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seed(args.root), indent=2))


if __name__ == "__main__":
    main()
