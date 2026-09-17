"""Phase 06 environment smoke test.

Confirms the pinned backend stack (spec §6) is actually importable after a
fresh `pip install`, and that the Phase 04 data-contract package still
imports cleanly. This is the automated counterpart to a manual pip-install
transcript -- it gives "fresh installation works" a check that fails loudly
in CI/pytest rather than relying on someone re-reading install logs.
"""

from __future__ import annotations

import importlib


def test_pinned_dependencies_import() -> None:
    for module_name in ("fastapi", "uvicorn", "pydantic", "networkx", "numpy", "pandas", "scipy"):
        importlib.import_module(module_name)


def test_data_contracts_package_imports() -> None:
    models = importlib.import_module("backend.app.models")
    assert hasattr(models, "Packet")
    assert hasattr(models, "TopologyGraph")
    assert hasattr(models, "Experiment")


def test_networkx_basic_graph_operations_work() -> None:
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    assert nx.has_path(graph, "a", "c")
    assert list(nx.shortest_path(graph, "a", "c")) == ["a", "b", "c"]
