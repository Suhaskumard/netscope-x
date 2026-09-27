"""Phase 106: one-command reproducibility check for external audit.

    python -m scripts.run_reproducibility_check [--out repro_out] [--manifest repro/expected_results.json]
    python -m scripts.run_reproducibility_check --write-manifest     # regenerate the expected manifest from this run

Re-runs the project's own verification (pytest per layer, validate_data_contracts, check_ground_truth_boundary) and compares the
observed counts EXACTLY to the committed manifest. Exit code 0 only if everything matches. Containerized via repro/Dockerfile.
It re-runs the same suite on the same pinned dependencies; it is not an independent re-derivation of the results.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

LAYERS = ("backend/tests", "experiments/tests", "simulator/tests")
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed|deselected)")
_CONTRACTS = re.compile(r"(\d+) passed, \d+ failed, (\d+) total")


def parse_pytest_summary(output: str) -> dict[str, int]:
    """Counts from pytest's final summary line ('3 passed, 1 skipped in 0.2s'); all keys always present."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    lines = [ln for ln in output.strip().splitlines() if _COUNT.search(ln) and " in " in ln]
    if not lines:
        return counts
    for n, kind in _COUNT.findall(lines[-1]):
        key = "errors" if kind in ("error", "errors") else kind
        if key in counts:
            counts[key] = int(n)
    return counts


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_layer(root: Path, layer: str) -> dict:
    code, out = _run([sys.executable, "-m", "pytest", layer, "-q", "-p", "no:cacheprovider"], root)
    counts = parse_pytest_summary(out)
    return {**counts, "exit_code": code, "total": sum(counts.values())}


def run_gates(root: Path) -> dict:
    code, out = _run([sys.executable, "-m", "scripts.validate_data_contracts"], root)
    m = _CONTRACTS.findall(out)
    contracts = {"passed": int(m[-1][0]), "total": int(m[-1][1])} if m else {"passed": 0, "total": 0}
    contracts["exit_code"] = code
    code_b, out_b = _run([sys.executable, "-m", "scripts.check_ground_truth_boundary"], root)
    return {"data_contracts": contracts, "ground_truth_boundary": {"clean": code_b == 0, "exit_code": code_b}}


def compare(observed: dict, expected: dict) -> list[str]:
    """Human-readable mismatches between an observed run and the manifest (exact match required)."""
    problems: list[str] = []
    for layer, exp in expected["layers"].items():
        obs = observed["layers"].get(layer)
        if obs is None:
            problems.append(f"{layer}: not run")
            continue
        for k in ("passed", "failed", "skipped", "errors"):
            if obs[k] != exp[k]:
                problems.append(f"{layer}: {k} observed {obs[k]} != expected {exp[k]}")
        if obs["exit_code"] != 0:
            problems.append(f"{layer}: pytest exit code {obs['exit_code']}")
    for k in ("passed", "total"):
        if observed["gates"]["data_contracts"][k] != expected["gates"]["data_contracts"][k]:
            problems.append(f"data_contracts: {k} observed {observed['gates']['data_contracts'][k]} != expected {expected['gates']['data_contracts'][k]}")
    if observed["gates"]["data_contracts"]["exit_code"] != 0:
        problems.append("data_contracts: nonzero exit code")
    if not observed["gates"]["ground_truth_boundary"]["clean"]:
        problems.append("ground_truth_boundary: not clean")
    return problems


def _environment(root: Path) -> dict:
    _, commit = _run(["git", "rev-parse", "HEAD"], root)
    _, freeze = _run([sys.executable, "-m", "pip", "freeze"], root)
    return {"python": platform.python_version(), "platform": platform.platform(),
            "git_commit": commit.strip() if re.fullmatch(r"[0-9a-f]{40}\s*", commit) else None,
            "pip_freeze": freeze.strip().splitlines()}


def run_check(root: Path, layers: tuple[str, ...] = LAYERS) -> dict:
    return {"layers": {layer: run_layer(root, layer) for layer in layers}, "gates": run_gates(root), "environment": _environment(root)}


def render_markdown(report: dict) -> str:
    lines = ["# Reproducibility report", "", f"Result: **{'PASS' if report['pass'] else 'FAIL'}**", "",
             "| layer | passed | failed | skipped | errors |", "|---|---|---|---|---|"]
    for layer, r in report["observed"]["layers"].items():
        lines.append(f"| {layer} | {r['passed']} | {r['failed']} | {r['skipped']} | {r['errors']} |")
    g = report["observed"]["gates"]
    lines += ["", f"- validate_data_contracts: {g['data_contracts']['passed']}/{g['data_contracts']['total']}",
              f"- check_ground_truth_boundary: {'clean' if g['ground_truth_boundary']['clean'] else 'NOT clean'}"]
    if report["problems"]:
        lines += ["", "## Mismatches", *[f"- {p}" for p in report["problems"]]]
    env = report["observed"]["environment"]
    lines += ["", f"Python {env['python']} on {env['platform']}; commit {env['git_commit']}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("repro_out"))
    ap.add_argument("--manifest", type=Path, default=Path("repro/expected_results.json"))
    ap.add_argument("--write-manifest", action="store_true", help="record this run as the expected manifest (no comparison)")
    args = ap.parse_args()
    root = args.root.resolve()
    observed = run_check(root)
    if args.write_manifest:
        manifest = {"layers": {k: {c: v[c] for c in ("passed", "failed", "skipped", "errors")} for k, v in observed["layers"].items()},
                    "gates": observed["gates"]}
        manifest["gates"]["data_contracts"] = {k: observed["gates"]["data_contracts"][k] for k in ("passed", "total")}
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"manifest written to {args.manifest}")
        return 0
    expected = json.loads((root / args.manifest).read_text(encoding="utf-8")) if not args.manifest.is_absolute() else json.loads(args.manifest.read_text(encoding="utf-8"))
    problems = compare(observed, expected)
    report = {"pass": not problems, "problems": problems, "observed": observed, "expected": expected}
    out = args.out if args.out.is_absolute() else root / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "reproducibility_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "reproducibility_report.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
