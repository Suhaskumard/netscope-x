# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 01 (Research Problem Formalization) complete. Phase 02 (Research Questions and Hypotheses)
not started.

## Completed phases

- Phase 0 — Setup (environment inspection + initial scaffolding)
- Phase 01 — Research Problem Formalization (`docs/research/problem_definition.md`)

## Blocked phases

None.

## Known bugs

None yet — no code written.

## Architecture decisions

- Project interpreter will be pinned to Python 3.12.10 (system also has 3.14.7 available, but 3.12
  is the safer target for the pinned scientific stack: NumPy, SciPy, NetworkX, Scapy).
- Full 25-section project tree (`backend/`, `nettrace/`, `flowmind/`, `archaeology/`, `causal/`,
  `pathforge/`, `counterfactual/`, `simulator/`, `experiments/`, `frontend/`, etc.) intentionally
  NOT created yet — the spec's own architectural principles warn against unnecessary directories
  before there are requirements/data contracts (Phase 03/04) to justify them.

## Environment inspection (Phase 0 findings)

- OS: Windows 11 Home Single Language, build 10.0.26200
- Docker: 29.7.2 (installed, Docker Desktop)
- Python: 3.12.10 and 3.14.7 both on PATH
- Node.js: v22.14.0
- npm: 10.9.2
- git: 2.55.0.windows.5
- Chrome: installed at `C:\Program Files\Google\Chrome\Application\chrome.exe` (not on PATH; usable
  via Playwright / claude-in-chrome for later frontend testing phases)
- Repository: `D:\Netscope-X`, git-initialized, previously empty aside from the master spec PDF
  (`NETSCOPE (1).pdf`)

## Current test status

No tests exist yet.

## Current datasets

None yet — datasets are introduced starting Phase 14/16/19.

## Current metrics

None yet — no experiments have been run.

## Pending work

Next: Phase 02 — Research Questions and Hypotheses (measurable research questions + hypotheses for
topology reconstruction, behavioral inference, anomaly detection, temporal change detection,
dependency inference, failure propagation, counterfactual simulation — each with hypothesis,
variables, evaluation metric, experiment design). Not started; awaiting explicit request.
