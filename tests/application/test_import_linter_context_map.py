from __future__ import annotations

import tomllib
from pathlib import Path


def test_import_linter_lists_demand_analytics_among_application_roots() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    forbidden = next(
        c for c in contracts if c["name"] == "Application package internals are private"
    )
    roots = forbidden["source_modules"]
    assert "src.application.master_data" in roots
    assert "src.application.micromarket_loading" in roots
    assert "src.application.product_identity" in roots
    assert "src.application.visit_photo_review" in roots
    assert "src.application.visit_photo_grouping" in roots
    assert "src.application.demand_analytics" in roots
    app_roots = [r for r in roots if r.startswith("src.application.")]
    assert len(app_roots) == 26


def test_context_map_does_not_ignore_unmatched_reference_data_package_edge() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    independence = next(c for c in contracts if c["name"] == "Application context map")
    ignores = independence["ignore_imports"]
    assert "src.application.reference_data -> src.application.master_data" not in ignores


def test_context_map_does_not_ignore_unmatched_reference_data_master_data_internals() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    independence = next(c for c in contracts if c["name"] == "Application context map")
    ignores = independence["ignore_imports"]
    assert "src.application.reference_data.** -> src.application.master_data.**" not in ignores


def test_reference_data_may_import_master_data_public_surface() -> None:
    from src.application.reference_data.master_data_export import (
        build_machines_mirror_export_rows,
    )

    assert callable(build_machines_mirror_export_rows)


def test_context_map_lists_master_data_and_allowed_edges() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    independence = next(c for c in contracts if c["name"] == "Application context map")
    assert "src.application.master_data" in independence["modules"]
    ignores = independence["ignore_imports"]
    assert "src.application.reference_data.** -> src.application.master_data" in ignores
    assert "src.application.master_data.** -> src.application.sheets" in ignores
    reverse = [
        item
        for item in ignores
        if "->" in item
        and "src.application.master_data" in item.split("->")[0]
        and "src.application.reference_data" in item.split("->")[1]
    ]
    assert reverse == []


def test_interfaces_must_not_import_master_data_internals() -> None:
    root = Path("src/interfaces/admin")
    forbidden = ("master_data.commands", "master_data.hydrate", "master_data.memory")
    hits: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.as_posix()}: {token}")
    assert hits == []
