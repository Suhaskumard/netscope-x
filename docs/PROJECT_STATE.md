# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 04 (Architecture and Data Contracts) complete. Phase 05 (Algorithm Selection) not started.

## Completed phases

- Phase 0 — Setup (environment inspection + initial scaffolding)
- Phase 01 — Research Problem Formalization (`docs/research/problem_definition.md`)
- Phase 02 — Research Questions and Hypotheses (`docs/research/research_questions.md`)
- Phase 03 — System Requirements (`docs/requirements/system_requirements.md`)
- Phase 04 — Architecture and Data Contracts (`backend/app/models/`,
  `docs/architecture/data_contracts.md`, validated by `scripts/validate_data_contracts.py`)

## Blocked phases

None.

## Known bugs

None yet — no code written.

## Architecture decisions

- Project interpreter will be pinned to Python 3.12.10 (system also has 3.14.7 available, but 3.12
  is the safer target for the pinned scientific stack: NumPy, SciPy, NetworkX, Scapy).
- Local dev virtual environment created at `.venv/` (Python 3.12.10), with `pydantic==2.9.2` pinned
  in `requirements.txt` — first real dependency of the project.
- `backend/app/models/` is the single shared location for all cross-module data contracts (Pydantic
  v2). NETTRACE, FLOWMIND, Archaeology, Causal, PathForge, Counterfactual, Experiments, and the API
  layer all import schemas from here rather than redefining their own. Rationale and full schema
  reference: `docs/architecture/data_contracts.md`.
- Data contracts encode several spec non-negotiable rules structurally (via required fields / model
  validators) rather than by convention alone — e.g., `Edge` cannot exist without `evidence`,
  `Anomaly.evidence` cannot be empty, `CounterfactualScenario.isolated_graph_id` cannot equal
  `baseline_graph_id`, `MetricResult` cannot exist without an `experiment_id`. See
  `docs/architecture/data_contracts.md` "Design principle" section for the full list.
- Remainder of the full 25-section project tree (`nettrace/`, `flowmind/`, `archaeology/`, `causal/`,
  `pathforge/`, `counterfactual/`, `simulator/`, `experiments/`, `frontend/`, etc.) still intentionally
  NOT created — those directories are justified once the phases that populate them (05+) are reached.

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

`scripts/validate_data_contracts.py` — 38/38 checks passed (19 schema types x valid+invalid case
each), run via `.venv/Scripts/python.exe -m scripts.validate_data_contracts`. No pytest suite exists
yet; that is introduced alongside the reproducible dev environment (Phase 06) and backend structure
(Phase 09+).

## Current datasets

None yet — datasets are introduced starting Phase 14/16/19.

## Current metrics

None yet — no experiments have been run.

## Pending work

Next: Phase 05 — Algorithm Selection (evaluate candidate algorithms for flow reconstruction, role
inference, anomaly detection, graph criticality, path analysis, dependency inference; document
alternatives, advantages, limitations, computational complexity, selected method). Not started;
awaiting explicit request.
