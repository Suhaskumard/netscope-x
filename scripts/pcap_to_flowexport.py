"""Convert a pcap into a NetFlow v5 or IPFIX export file with the project's software exporter (Phase 95):
    python -m scripts.pcap_to_flowexport in.pcap out.ipfix --format ipfix
The result can be staged in the upload inbox and ingested with POST /capture source=netflow_upload."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.nettrace.flowexport import ipfix, netflow_v5
from backend.nettrace.flowexport.exporter import export_pcap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--format", choices=["v5", "ipfix"], default="ipfix")
    args = parser.parse_args()
    records = export_pcap(args.pcap, ipv4_only=args.format == "v5")
    args.out.write_bytes((netflow_v5 if args.format == "v5" else ipfix).encode(records))
    print(f"wrote {len(records)} flow records to {args.out}")


if __name__ == "__main__":
    main()
