from __future__ import annotations

import ast
from pathlib import Path


def test_wire_settlement_does_not_import_wire_matrix_worker_for_snapshot_store() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "infrastructure"
        / "composition"
        / "wiring"
        / "wire_settlement.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
            for alias in node.names:
                imported_names.add(alias.name)

    assert "build_apply_snack_sale" in imported_names
    assert "build_matrix_snapshot_store" not in imported_names
    assert not any(module.endswith("wire_matrix_worker") for module in imported_modules)


def test_settlement_factory_imports_snapshot_store_from_persistence() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "infrastructure"
        / "composition"
        / "factories"
        / "settlement.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    snapshot_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                if alias.name == "build_matrix_snapshot_store":
                    snapshot_imports.append(node.module)

    assert snapshot_imports == [
        "src.infrastructure.composition.factories.persistence",
    ]
    assert not any(module.endswith("wire_matrix_worker") for module in snapshot_imports)
