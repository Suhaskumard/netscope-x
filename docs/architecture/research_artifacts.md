# NETSCOPE-X — Research Artifact Architecture

Phase 10 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 10 — RESEARCH ARTIFACT
ARCHITECTURE"). Defines reproducible on-disk formats for all 8 required artifact types: PCAP, flows,
ground truth, graphs, snapshots, experiments, results, metrics. Code: `experiments/artifacts/`.
Verified by `experiments/tests/test_artifacts.py` (8 tests, all passing).

This is distinct from two earlier phases that look similar:
- **Phase 04** (`docs/architecture/data_contracts.md`) defines what each object *is* (in-memory
  Pydantic schema).
- **Phase 09** (`docs/architecture/api_design.md`) defines how a client asks for one *over HTTP*.
- **Phase 10** (this document) defines how it's *persisted to disk* reproducibly.

## Storage choice: files, not a database

Per spec §6 ("choose the minimum persistence architecture necessary... do not introduce
PostgreSQL/Neo4j/Redis/etc. merely because they sound impressive"): no pipeline exists yet to produce
or query these artifacts at any real scale — that starts Phase 21. A flat, versioned, file-based
layout (JSON for single objects, JSON Lines for collections) is the correct minimum today. This will
be revisited only if a concrete, measured need (e.g. large-dataset query performance) justifies
introducing a database — not speculatively now.

## Directory layout

```
<root>/
  captures/<capture_id>/
    raw.pcap                       # Phase 21+: raw packet capture
    flows.jsonl                    # Phase 23+: one Flow per line
    topology/<graph_id>.json       # Phase 32+: one TopologyGraph
    snapshots/<snapshot_id>.json   # Phase 44+: one NetworkSnapshot
  ground_truth/<capture_id>/
    topology.json                  # Phase 16+: authoritative ground truth
    topology.json.sha256           # content-hash sidecar (spec Phase 17)
  experiments/<experiment_id>/
    experiment.json                # one Experiment (spec §20 reproducibility fields)
    metrics.jsonl                  # one MetricResult per line (results)
```

`root` is always an explicit parameter to every path-building function in `paths.py` — never a
hardcoded global path (NFR-4). Once a real deployment need exists, `root` can be sourced from
`Settings` (Phase 08); that wiring isn't added speculatively here.

## I/O layer (`experiments/artifacts/io.py`)

Three generic shapes cover every artifact type — no per-type bespoke serializer:

- **`write_json`/`read_json`** — single Pydantic object ↔ one `.json` file (topology graphs,
  snapshots, experiments).
- **`write_jsonl`/`read_jsonl`** — a collection of Pydantic objects ↔ one newline-delimited `.jsonl`
  file, one JSON object per line (flows, metrics/results). JSON Lines is chosen over a single JSON
  array so large collections can, in a later phase, be streamed/appended without rewriting the whole
  file.
- **`write_ground_truth`/`read_ground_truth`** — same JSON serialization as `write_json`/`read_json`,
  plus a `<filename>.sha256` sidecar file containing the SHA-256 hex digest of the JSON content.
  `read_ground_truth` **always** recomputes the hash and compares it to the sidecar before returning
  data; a missing sidecar or a mismatch raises `GroundTruthIntegrityError` rather than silently
  returning (possibly contaminated) data. This is the concrete mechanism spec Phase 17 requires
  ("version and hash ground-truth artifacts; prevent accidental contamination of inference") and it
  directly supports the ground-truth rule from `docs/research/problem_definition.md` §2/§6: ground
  truth may be used for evaluation, never leaked into inference — if a ground-truth file were ever
  accidentally edited by inference-path code, the very next read would fail loudly instead of silently
  succeeding with corrupted data.

## PCAP

No PCAP reading/writing code exists yet (that's spec Phase 21, High-Fidelity Packet Capture). This
phase only fixes the *location* convention (`captures/<capture_id>/raw.pcap`) so that Phase 21's
capture code and any later phase reading it agree on where a given capture's raw file lives, keyed by
the same `capture_id` already present on the `Packet`/`Flow` schemas (Phase 04).

## Verification performed this phase

- `pytest experiments/tests/test_artifacts.py` — 8/8 passed: round-trip write/read for flows (JSON
  Lines), a topology graph, a network snapshot, an experiment + its metrics, and a ground-truth
  topology object — all using real Phase 04 model instances written to and read from a real temporary
  directory (pytest's `tmp_path`), not mocked I/O. Two dedicated integrity tests: tampering with a
  ground-truth file's on-disk content after writing correctly raises `GroundTruthIntegrityError`;
  deleting the `.sha256` sidecar correctly raises the same error rather than silently reading
  unverified data.
- `pytest backend/tests experiments/tests` (combined, 48 tests) — all passed, no regression from
  Phases 06–09.

## Known limitations

- No real dataset registry (`dataset_small`, `dataset_medium`, ... per spec §19) exists yet — this
  phase's I/O layer is the foundation Phase 19's dataset generator will build on, not the dataset
  system itself.
- No PCAP artifacts have actually been written or read — only the path convention is fixed; real
  PCAP I/O is Phase 21.
- `root` is a plain parameter, not yet wired to `Settings` (Phase 08) — no code yet needs a single
  configured artifact root, so this wiring is deferred rather than added speculatively.

## Status

This document, together with `experiments/artifacts/{paths,io}.py` and
`experiments/tests/test_artifacts.py`, satisfies Phase 10: reproducible formats for all 8 required
artifact types are defined and verified by actually running the round-trip test suite.
