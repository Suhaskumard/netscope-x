# Reproducibility package (Phase 106)

One command re-runs the project's own verification for an external auditor:

    sh repro/run.sh            # or: powershell repro/run.ps1
    # = docker build -f repro/Dockerfile -t netscope-repro .  &&  docker run --rm -v ./repro_out:/app/repro_out netscope-repro

Without Docker: `python -m scripts.run_reproducibility_check` (needs `pip install -r requirements-dev.txt`).

**What it does.** `scripts/run_reproducibility_check.py` runs pytest separately for `backend/tests`, `experiments/tests` and
`simulator/tests`, then `scripts.validate_data_contracts` and `scripts.check_ground_truth_boundary`, and compares the observed
passed/failed/skipped/error counts EXACTLY to the committed `repro/expected_results.json`. It writes
`repro_out/reproducibility_report.{json,md}` (including python version, `pip freeze`, git commit when available) and exits non-zero on
any mismatch or failure. `--write-manifest` regenerates the manifest from a real run (used once per phase, after adding tests).

**What it proves.** The same suite, on the pinned `requirements.txt` versions in a clean python:3.12 image, gives the same counts and
pass/fail status as reported in `docs/PROJECT_STATE.md`.
**What it does not.** It is not an independent re-derivation: the tests are the project's own. It does not re-run the long
experiment studies (drift, significance, calibration, benchmarks) - only their tests; those have their own `scripts/run_*` entry
points. Tests needing a live interface or a Docker lab skip with an explicit reason, and skips are counted in the manifest.
