"""Encrypted traffic metadata: real TLS version extraction (spec Phase 27, FR-1.7).

Four of FR-1.7's five named items (duration, sizes, timing, endpoint
relationships) are already real via Phase 23/25's Flow/FlowFeatures; this
module supplies the fifth: TLS version. A ServerHello handshake message is
never encrypted in any TLS version -- encryption only begins after the
handshake completes -- so parsing its cleartext header and
`supported_versions` extension (which carries the real negotiated version
for TLS 1.3, since the legacy version field stays pinned to 0x0303 for
compatibility) is genuine metadata extraction, never decryption.

Independent of `normalize.py`'s persisted `Packet` schema (which
deliberately carries no payload) -- re-reads `raw.pcap` directly via
`PcapReader`, the same convention `normalize.py` already uses, purely as a
best-effort enrichment lookup. See
`docs/architecture/encrypted_traffic_metadata.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from scapy.layers.inet import IP, TCP
from scapy.utils import PcapReader

from experiments.artifacts.paths import pcap_path

# (major, minor) -> human label. TLS 1.3's real negotiated version only
# appears in the supported_versions extension; ServerHello's own
# legacy_version field stays 0x0303 ("TLS 1.2") for compatibility even when
# 1.3 is what's actually negotiated.
_VERSION_NAMES = {
    (3, 1): "TLS 1.0",
    (3, 2): "TLS 1.1",
    (3, 3): "TLS 1.2",
    (3, 4): "TLS 1.3",
}


def _parse_server_hello_version(payload: bytes) -> Optional[str]:
    """Parses one TCP segment's payload as a TLS record containing a
    ServerHello, returning the real negotiated version if found. Returns
    None for anything else: a different record/message type, a ServerHello
    split across TCP segments (not reassembled -- documented limitation),
    or too short to contain what's being parsed. Never reads past the
    ServerHello's own cleartext header/extensions.
    """
    if len(payload) < 5 or payload[0] != 0x16 or payload[1] != 3:
        return None
    record_len = int.from_bytes(payload[3:5], "big")
    if len(payload) < 5 + record_len:
        return None

    body = payload[5 : 5 + record_len]
    if len(body) < 4 or body[0] != 0x02:  # 0x02 = ServerHello
        return None
    hs_len = int.from_bytes(body[1:4], "big")
    hello = body[4 : 4 + hs_len]
    if len(hello) < 2:
        return None

    legacy_version = _VERSION_NAMES.get((hello[0], hello[1]))

    # ServerHello body: 2(version) + 32(random) + 1+session_id_len +
    # 2(cipher_suite) + 1(compression_method) + 2(extensions_len) + extensions.
    offset = 2 + 32
    if len(hello) <= offset:
        return legacy_version
    session_id_len = hello[offset]
    offset += 1 + session_id_len + 2 + 1
    if len(hello) < offset + 2:
        return legacy_version
    ext_total_len = int.from_bytes(hello[offset : offset + 2], "big")
    offset += 2
    extensions = hello[offset : offset + ext_total_len]

    pos = 0
    while pos + 4 <= len(extensions):
        ext_type = int.from_bytes(extensions[pos : pos + 2], "big")
        ext_len = int.from_bytes(extensions[pos + 2 : pos + 4], "big")
        ext_body = extensions[pos + 4 : pos + 4 + ext_len]
        if ext_type == 0x002B and len(ext_body) >= 2:  # supported_versions
            return _VERSION_NAMES.get((ext_body[0], ext_body[1]), legacy_version)
        pos += 4 + ext_len

    return legacy_version


def extract_tls_versions(root: Path, capture_id: str) -> Dict[Tuple[str, int], str]:
    """Scans `raw.pcap` for real ServerHello messages, keyed by the
    server's own (ip, port) -- a ServerHello is always server->client, so
    this identifies the version regardless of which five-tuple orientation
    `reconstruct_flows` later canonicalizes as forward/reverse.
    """
    versions: Dict[Tuple[str, int], str] = {}
    with PcapReader(str(pcap_path(root, capture_id))) as reader:
        for pkt in reader:
            if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
                continue
            payload = bytes(pkt[TCP].payload)
            if not payload:
                continue
            version = _parse_server_hello_version(payload)
            if version is not None:
                versions[(pkt[IP].src, pkt[TCP].sport)] = version
    return versions
