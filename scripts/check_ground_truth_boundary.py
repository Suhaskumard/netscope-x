"""Structural safeguard against ground-truth contamination of the inference pipeline
(spec Phase 17: "prevent accidental contamination of inference"; spec §4, the ground-truth
rule -- "It MUST NOT leak into the inference pipeline").

Walks every `.py` file in the repository, parses it with `ast`, and flags any import of
`simulator.ground_truth` (module or submodule) whose *importing* file lives outside an explicit
allowlist of spec-sanctioned uses (generating experiments, validating results, calculating
metrics, checking reconstruction accuracy): `simulator/`, `experiments/`, `scripts/`, and test
directories anywhere in the tree.

Inference code (`nettrace/`, `flowmind/`, `backend/app/services/`, ...) doesn't exist yet -- it
starts spec Phase 21+ -- so this currently passes trivially. That is the point: it is a guardrail
that fails loudly the day such code first imports ground truth, rather than a check of something
that has already gone wrong.

Run with:
    .venv/Scripts/python.exe -m scripts.check_ground_truth_boundary
(from the repository root).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, NamedTuple

EXCLUDED_DIR_NAMES = {".venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}

ALLOWED_IMPORTER_PREFIXES = ("simulator", "experiments", "scripts")

FORBIDDEN_MODULE = "simulator.ground_truth"


class Violation(NamedTuple):
    file: Path
    line: int
    imported: str


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _is_allowed_importer(relative_path: Path) -> bool:
    parts = relative_path.parts
    if parts and parts[0] in ALLOWED_IMPORTER_PREFIXES:
        return True
    return "tests" in parts


def _imports_forbidden_module(node: ast.stmt) -> List[str]:
    """Returns the dotted names this import statement pulls in that are, or are a submodule
    of, the forbidden module."""
    hits: List[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == FORBIDDEN_MODULE or alias.name.startswith(FORBIDDEN_MODULE + "."):
                hits.append(alias.name)
    elif isinstance(node, ast.ImportFrom) and node.module:
        module = node.module
        if module == FORBIDDEN_MODULE or module.startswith(FORBIDDEN_MODULE + "."):
            hits.append(module)
        elif module == "simulator":
            # from simulator import ground_truth
            for alias in node.names:
                if alias.name == "ground_truth":
                    hits.append(f"{module}.{alias.name}")
    return hits


def find_violations(repo_root: Path) -> List[Violation]:
    violations: List[Violation] = []
    for py_file in repo_root.rglob("*.py"):
        relative = py_file.relative_to(repo_root)
        if _is_excluded(relative):
            continue
        if _is_allowed_importer(relative):
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for imported in _imports_forbidden_module(node):
                    violations.append(Violation(file=relative, line=node.lineno, imported=imported))

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    violations = find_violations(repo_root)

    if not violations:
        print("OK: no import of simulator.ground_truth found outside the allowed generation/evaluation/test code.")
        return 0

    print("GROUND-TRUTH BOUNDARY VIOLATION(S) FOUND:")
    for v in violations:
        print(f"  {v.file}:{v.line}: imports {v.imported!r}")
    print(
        "\nGround truth must only be used for generating experiments, validating results, "
        "calculating metrics, or checking reconstruction accuracy (spec §4) -- never imported "
        "by inference code."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
