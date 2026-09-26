"""Query the telemetry the platform emitted about itself (spec Phase 94): reads traces.jsonl / metrics.jsonl."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    start: datetime
    end: datetime
    attributes: dict[str, Any]
    status: str

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start).total_seconds() * 1000.0


@dataclass(frozen=True)
class MetricPoint:
    name: str
    attributes: dict[str, Any]
    value: Optional[float]  # counters: the cumulative sum
    count: Optional[int]  # histograms: number of recordings
    sum: Optional[float]  # histograms: sum of recorded values


def _lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def spans(out_dir: Path, name: Optional[str] = None, trace_id: Optional[str] = None, **attrs) -> list[Span]:
    out = []
    for raw in _lines(Path(out_dir) / "traces.jsonl"):
        s = Span(
            name=raw["name"],
            trace_id=raw["context"]["trace_id"],
            span_id=raw["context"]["span_id"],
            parent_id=raw.get("parent_id"),
            start=datetime.fromisoformat(raw["start_time"].replace("Z", "+00:00")),
            end=datetime.fromisoformat(raw["end_time"].replace("Z", "+00:00")),
            attributes=raw.get("attributes") or {},
            status=raw["status"]["status_code"],
        )
        if (name is None or s.name == name) and (trace_id is None or s.trace_id == trace_id) and all(
            s.attributes.get(k) == v for k, v in attrs.items()
        ):
            out.append(s)
    return out


def children(all_spans: list[Span], parent: Span) -> list[Span]:
    return [s for s in all_spans if s.parent_id == parent.span_id and s.trace_id == parent.trace_id]


def metric_points(out_dir: Path, name: Optional[str] = None, **attrs) -> list[MetricPoint]:
    """Points from the most recent metrics snapshot (values are cumulative)."""
    snapshots = _lines(Path(out_dir) / "metrics.jsonl")
    if not snapshots:
        return []
    out = []
    for rm in snapshots[-1]["data"]["resource_metrics"]:
        for sm in rm["scope_metrics"]:
            for metric in sm["metrics"]:
                if name is not None and metric["name"] != name:
                    continue
                for dp in metric["data"]["data_points"]:
                    a = dp.get("attributes") or {}
                    if all(a.get(k) == v for k, v in attrs.items()):
                        out.append(MetricPoint(metric["name"], a, dp.get("value"), dp.get("count"), dp.get("sum")))
    return out
