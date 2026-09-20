# NETSCOPE-X — Testing Guide

Phase 69 documentation deliverable.

## Running the suite

```bash
pytest backend/tests experiments/tests simulator/tests -q
```

As of Phase 69: **625 tests, all real** (no mocked business logic — the project's own non-negotiable
rule, restated every phase). Breakdown by layer:

| Layer | What it covers |
|---|---|
| `backend/tests/` (44 files) | Every NETTRACE/FLOWMIND/Archaeology/Dependency/Digital-Twin/Simulation module, plus `test_api.py` (route behavior, error envelopes, path-traversal/interface-authorization checks) and `test_config.py`/`test_environment_smoke.py` |
| `experiments/tests/` (11 files) | Artifact I/O, synthetic traffic generation, every evaluation metric module, and the full matrix runner |
| `simulator/tests/` (8 files) | Lab traffic/protocol generators, scenario generation, ground-truth generation + integrity, controlled live capture (interface authorization and now interface-unavailable handling) |

## Other verification gates

Run these after any change touching Pydantic models or the ground-truth/inference boundary:

```bash
python -m scripts.validate_data_contracts     # Pydantic round-trip + valid/invalid construction checks (55/55)
python -m scripts.check_ground_truth_boundary # static import-boundary guard (spec §4) — no clean/dirty import
```

Both are re-run as part of every phase's own completion check, and were re-verified clean in Phase 69
after this phase's changes (the `CAPTURE_ID_PATTERN` fix, the `InterfaceUnavailableError` fix, and the
`matrix_runner.py`/`failure.py` unused-import cleanup).

## What "real, not mocked" means here

Every test constructs real Pydantic models, runs the real algorithm under test (NetworkX graph
algorithms, real Scapy packet construction via `wrpcap`/`IP`/`TCP`/`UDP`, real statistical
computations), and asserts on real output — never a stubbed return value standing in for the logic
being tested. Where a test needs a live external resource unavailable in this environment (a Docker
lab, a real network interface), it says so explicitly in its own docstring rather than mocking that
resource and asserting against the mock (see `simulator/tests/test_capture.py`'s module docstring for
the clearest example of this pattern).

## Static checks used ad hoc (not wired into CI — no CI is configured in this repository)

```bash
python -m pyflakes backend/ experiments/ simulator/   # unused-import / unused-variable scan
```

Used during Phase 69's cleanup pass; found and fixed 2 real unused imports in production code
(`backend/app/models/failure.py`, `experiments/matrix_runner.py`). No `TODO`/`FIXME`/stray debug
`print()` was found in production code as of Phase 69 (a repo-wide `grep` pass).

## What is not covered by this test suite

See `docs/acceptance_testing.md` for the full requirement-level breakdown. In summary: PERF-1..7
(no benchmarking exists to test), REL-11 (large-dataset behavior, ties to the same benchmarking gap),
and anything requiring a real Docker lab or browser (see `docs/LIMITATIONS.md`).
