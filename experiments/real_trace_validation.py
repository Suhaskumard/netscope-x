"""Cross-domain validation against user-supplied real pcaps (spec addendum Phase 103).

Real traces carry NO ground-truth topology, so nothing here is "accuracy against truth". Every number is a proxy, labeled as one:

* pipeline accounting: frames read vs packets normalized vs flows/nodes/edges, with unexplained drops counted (a real defect signal);
* edge recovery against the flow record itself (every edge should be supported by a flow and every flow should land on an edge);
* role agreement with a transparent well-known-port labeler under leave-one-node-out, next to the majority-class baseline (the
  labeler uses ports the classifier can also see, so agreement is inflated; the report says so);
* stability under packet subsampling (edge-set Jaccard and node retention vs the full trace), computed by the SAME function on a
  synthetic capture so the real-vs-synthetic gap is one table. Synthetic truth-based edge F1 is shown for context only.

A trace that fails to parse is reported FAILED with the exception class, never skipped silently. With no pcaps the result is
NOT_RUN and no number is produced. Never imports `simulator.ground_truth`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from backend.app.models.behavior import ObservationWindow, ServiceRole
from backend.app.models.packet import Packet
from backend.dependency.strength import estimate_dependency_strength
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.capture.ingest import ingest_pcap
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import read_jsonl, write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.metrics.role_heldout import evaluate_role_held_out
from experiments.observation_sampling import sample_packets

COMPLETENESS_LEVELS = (1.0, 0.75, 0.5, 0.25)
DEFAULT_MAX_BYTES = 200 * 1024 * 1024  # ingest reads the whole file into memory
CAVEAT = ("Real traces have no ground-truth topology: every number below is a proxy measure, not accuracy against truth. "
          "Results describe only the traces supplied.")

_SERVER_PORT_ROLES = {5432: ServiceRole.DATABASE, 6379: ServiceRole.CACHE, 53: ServiceRole.DNS,
                      80: ServiceRole.API, 443: ServiceRole.API, 8080: ServiceRole.API, 8443: ServiceRole.API}
_Pair = FrozenSet[FrozenSet[str]]


def _capture_id(index: int, path: Path) -> str:
    return f"real-{index:02d}-" + re.sub(r"[^A-Za-z0-9_-]", "_", path.stem)[:60]


def count_frames(path: Path) -> Tuple[int, int]:
    """(total frames, frames with an IPv4/IPv6 layer), streamed, independent of the pipeline's normalizer."""
    from scapy.layers.inet import IP
    from scapy.layers.inet6 import IPv6
    from scapy.utils import PcapReader

    total = ip = 0
    with PcapReader(str(path)) as reader:
        for pkt in reader:
            total += 1
            if pkt.haslayer(IP) or pkt.haslayer(IPv6):
                ip += 1
    return total, ip


def _node_ips(node) -> FrozenSet[str]:
    return frozenset(str(i) for i in node.ip_addresses)


def _edge_pairs(graph) -> Set[_Pair]:
    ips = {n.node_id: _node_ips(n) for n in graph.nodes}
    return {frozenset({ips[e.source_node_id], ips[e.target_node_id]}) for e in graph.edges}


def edge_recovery(graph, flows) -> Dict[str, Any]:
    """Flow record vs graph: flows landing on an edge, and edges with no supporting flow."""
    owner = {ip: ips for n in graph.nodes for ips in [_node_ips(n)] for ip in ips}
    edges = _edge_pairs(graph)
    flow_pairs = [frozenset({owner.get(str(f.src_ip), frozenset({str(f.src_ip)})), owner.get(str(f.dst_ip), frozenset({str(f.dst_ip)}))}) for f in flows]
    covered = sum(1 for p in flow_pairs if p in edges)
    unsupported = len(edges - set(flow_pairs))
    return {"flows": len(flows), "flows_on_an_edge": covered,
            "flow_edge_coverage": (covered / len(flows)) if flows else None, "edges_without_supporting_flow": unsupported}


def port_role_labels(flows, graph) -> Dict[str, ServiceRole]:
    """Transparent proxy labels: a node serving a well-known port gets that role (most flows wins); a node that only ever
    initiates gets CLIENT; anything else stays unlabeled rather than guessed."""
    owner = {str(ip): n.node_id for n in graph.nodes for ip in n.ip_addresses}
    served: Dict[str, Counter] = {n.node_id: Counter() for n in graph.nodes}
    receives: Set[str] = set()
    initiates: Set[str] = set()
    for f in flows:
        s, d = owner.get(str(f.src_ip)), owner.get(str(f.dst_ip))
        if s:
            initiates.add(s)
        if d:
            receives.add(d)
            if f.dst_port in _SERVER_PORT_ROLES:
                served[d][_SERVER_PORT_ROLES[f.dst_port]] += 1
    labels: Dict[str, ServiceRole] = {}
    for node_id, counts in served.items():
        if counts:
            labels[node_id] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].value))[0][0]
        elif node_id in initiates and node_id not in receives:
            labels[node_id] = ServiceRole.CLIENT
    return labels


def role_agreement(flows, graph) -> Dict[str, Any]:
    labels = port_role_labels(flows, graph)
    dist = Counter(r.value for r in labels.values())
    out: Dict[str, Any] = {"labeled_nodes": len(labels), "total_nodes": len(graph.nodes), "label_distribution": dict(dist),
                           "note": "proxy labels from well-known ports; inflated because the classifier also sees ports"}
    if len(labels) < 2:
        out["status"] = "insufficient_labeled_nodes"
        return out
    computed_at: datetime = max(f.last_seen for f in flows)
    by_id = {n.node_id: n for n in graph.nodes}
    labeled = [(assemble_node_fingerprint(flows, by_id[nid], ObservationWindow.MEDIUM, computed_at=computed_at), role)
               for nid, role in sorted(labels.items())]
    ev = evaluate_role_held_out(labeled)
    out.update(status="ok", held_out_accuracy_seen_roles=ev.held_out_accuracy_seen_roles, unseen_role_fold_count=ev.unseen_role_fold_count,
               fold_count=ev.fold_count, majority_class_baseline=max(dist.values()) / len(labels), held_out=asdict(ev.held_out))
    return out


def _graph_for(root: Path, capture_id: str):
    reconstruct_flows(root, capture_id)
    return build_topology_graph(root, capture_id, graph_id=capture_id)


def stability(root: Path, capture_id: str, seed: int, levels=COMPLETENESS_LEVELS) -> List[Dict[str, Any]]:
    """Edge-set Jaccard and node retention of subsampled reruns vs the full capture. Same function for real and synthetic."""
    full_packets = read_jsonl(packets_path(root, capture_id), Packet)
    full = _graph_for(root, capture_id)
    full_edges, full_nodes = _edge_pairs(full), {_node_ips(n) for n in full.nodes}
    rows = []
    for c in levels:
        sub = f"{capture_id}-c{int(round(c * 100))}"
        write_jsonl(packets_path(root, sub), sample_packets(full_packets, c, seed))
        g = _graph_for(root, sub)
        edges, nodes = _edge_pairs(g), {_node_ips(n) for n in g.nodes}
        union = edges | full_edges
        rows.append({"completeness": c, "edge_jaccard": (len(edges & full_edges) / len(union)) if union else 1.0,
                     "node_retention": (len(nodes & full_nodes) / len(full_nodes)) if full_nodes else 1.0,
                     "edges": len(edges), "nodes": len(nodes)})
    return rows


def labeled_edge_scores(graph, truth_edges: List[List[str]]) -> Dict[str, Any]:
    """Optional user-supplied labels: {'edges': [[ip, ip], ...]}. Precision/recall over IP pairs."""
    truth = [(a, b) for a, b in truth_edges]
    ips = {n.node_id: _node_ips(n) for n in graph.nodes}
    inferred = [(ips[e.source_node_id], ips[e.target_node_id]) for e in graph.edges]

    def hits(pair, a, b):
        return (pair[0] in a and pair[1] in b) or (pair[0] in b and pair[1] in a)

    tp = sum(1 for a, b in inferred if any(hits(t, a, b) for t in truth))
    covered = sum(1 for t in truth if any(hits(t, a, b) for a, b in inferred))
    p = tp / len(inferred) if inferred else 0.0
    r = covered / len(truth) if truth else 0.0
    return {"edge_precision": p, "edge_recall": r, "edge_f1": (2 * p * r / (p + r)) if p + r else 0.0,
            "inferred_edges": len(inferred), "truth_edges": len(truth), "source": "user-supplied labels file"}


def validate_trace(path: Path, root: Path, index: int, seed: int, max_bytes: int, labels: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"trace": path.name, "size_bytes": path.stat().st_size}
    if result["size_bytes"] > max_bytes:
        return {**result, "status": "REFUSED", "reason": f"file exceeds the {max_bytes}-byte cap (ingest reads it whole)"}
    cid = _capture_id(index, path)
    try:
        ingest_pcap(path, root, cid, original_filename=path.name)
        ensure_packets(root, cid)
        packets = read_jsonl(packets_path(root, cid), Packet)
        total, ip_frames = count_frames(path)
        flows = reconstruct_flows(root, cid)
        graph = build_topology_graph(root, cid, graph_id=cid)
        estimate_dependency_strength(root, cid)
        result.update(
            status="OK", capture_id=cid,
            accounting={"frames": total, "ip_frames": ip_frames, "non_ip_skipped": total - ip_frames, "packets_normalized": len(packets),
                        "unexplained_drops": ip_frames - len(packets), "flows": len(flows), "nodes": len(graph.nodes), "edges": len(graph.edges)},
            edge_recovery=edge_recovery(graph, flows), role_agreement=role_agreement(flows, graph) if flows else {"status": "no_flows"},
            stability=stability(root, cid, seed))
        if labels and path.name in labels:
            result["labeled_edge_scores"] = labeled_edge_scores(graph, labels[path.name]["edges"])
    except Exception as exc:  # reported, not swallowed: the class and message go into the report
        result.update(status="FAILED", error=type(exc).__name__, reason=str(exc)[:300])
    return result


def synthetic_reference(root: Path, seed: int) -> Dict[str, Any]:
    """The same stability function on a synthetic capture, plus the truth-based edge F1 the lab reports at each completeness."""
    from experiments.matrix_runner import run_matrix_cell

    cell = run_matrix_cell(root, "small", 1.0, seed=seed, capture_id="synthetic-ref", evaluate_anomaly=False)
    rows = stability(root, "synthetic-ref", seed)
    truth = {}
    for c in COMPLETENESS_LEVELS:
        cc = run_matrix_cell(root, "small", c, seed=seed, capture_id=f"synthetic-truth-{int(round(c * 100))}", evaluate_anomaly=False)
        truth[c] = cc.raw_evaluations["topology_reconstruction"]["edge_f1"]
    del cell
    return {"topology": "small", "stability": rows, "truth_based_edge_f1_by_completeness": truth,
            "note": "truth-based F1 exists only for synthetic data and is not comparable to the stability proxy"}


def _mean(xs: List[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def compare(traces: List[Dict[str, Any]], synthetic: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per completeness: mean real vs synthetic stability, flagging every case where real is worse."""
    ok = [t for t in traces if t["status"] == "OK"]
    rows = []
    for i, s in enumerate(synthetic["stability"]):
        real_j = _mean([t["stability"][i]["edge_jaccard"] for t in ok])
        real_n = _mean([t["stability"][i]["node_retention"] for t in ok])
        rows.append({"completeness": s["completeness"], "real_edge_jaccard": real_j, "synthetic_edge_jaccard": s["edge_jaccard"],
                     "real_node_retention": real_n, "synthetic_node_retention": s["node_retention"],
                     "real_worse": real_j is not None and real_j < s["edge_jaccard"]})
    return rows


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Real-trace validation (Phase 103)", "", f"> {CAVEAT}", ""]
    if report["status"] == "NOT_RUN":
        return "\n".join(lines + [f"**NOT RUN**: {report['reason']}", ""])
    for t in report["traces"]:
        lines.append(f"## {t['trace']} — {t['status']}")
        if t["status"] != "OK":
            lines += [f"{t.get('error', '')} {t.get('reason', '')}", ""]
            continue
        a = t["accounting"]
        lines.append(f"frames {a['frames']} (non-IP skipped {a['non_ip_skipped']}, unexplained drops {a['unexplained_drops']}), "
                     f"flows {a['flows']}, nodes {a['nodes']}, edges {a['edges']}")
        er = t["edge_recovery"]
        lines.append(f"edge recovery: flow→edge coverage {er['flow_edge_coverage']}, edges without supporting flow {er['edges_without_supporting_flow']}")
        ra = t["role_agreement"]
        lines.append(f"role agreement (proxy): {ra.get('status')} held-out accuracy {ra.get('held_out_accuracy_seen_roles')} "
                     f"vs majority baseline {ra.get('majority_class_baseline')}; labeled {ra.get('labeled_nodes')}/{ra.get('total_nodes')}")
        lines.append("stability: " + "; ".join(f"{r['completeness']}: J={r['edge_jaccard']:.3f} nodes={r['node_retention']:.3f}" for r in t["stability"]))
        if "labeled_edge_scores" in t:
            lines.append(f"labeled edge scores: {t['labeled_edge_scores']}")
        lines.append("")
    lines += ["## Real vs synthetic (same stability function)", "", "| completeness | real edge J | synthetic edge J | real worse |", "|---|---|---|---|"]
    for r in report["comparison"]:
        rj = "n/a" if r["real_edge_jaccard"] is None else f"{r['real_edge_jaccard']:.3f}"
        lines.append(f"| {r['completeness']} | {rj} | {r['synthetic_edge_jaccard']:.3f} | {r['real_worse']} |")
    return "\n".join(lines + [""])


def run_validation(traces_dir: Path, root: Path, seed: int = 42, max_bytes: int = DEFAULT_MAX_BYTES,
                   labels_path: Optional[Path] = None) -> Dict[str, Any]:
    pcaps = sorted(p for p in traces_dir.glob("*") if p.is_file() and p.suffix.lower() in (".pcap", ".pcapng", ".cap")) if traces_dir.is_dir() else []
    out_dir = root / "real_trace_validation"
    if not pcaps:
        report: Dict[str, Any] = {"status": "NOT_RUN", "reason": f"no .pcap/.pcapng/.cap files found in {traces_dir}; supply real traces to run", "caveat": CAVEAT}
    else:
        labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path else None
        traces = [validate_trace(p, root, i, seed, max_bytes, labels) for i, p in enumerate(pcaps)]
        synthetic = synthetic_reference(root, seed)
        report = {"status": "OK", "caveat": CAVEAT, "seed": seed, "traces": traces, "synthetic": synthetic, "comparison": compare(traces, synthetic)}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
