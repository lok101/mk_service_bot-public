from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_INTERFACE_ROOT = _REPO_ROOT / "src" / "interfaces" / "admin"
_ADMIN_INTERFACE_PY = sorted(
    path for path in _ADMIN_INTERFACE_ROOT.rglob("*.py") if "__pycache__" not in path.parts
)


def _relative_id(module_path: Path) -> str:
    return module_path.relative_to(_REPO_ROOT).as_posix()


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
    return found


def _is_public_application_import(module: str) -> bool:
    parts = module.split(".")
    if parts[:2] != ["src", "application"]:
        return True
    return len(parts) == 3 or (
        len(parts) == 4 and (parts[3] == "ports" or parts[3].endswith("_ports"))
    )


def _application_import_violations_from_source(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    return [
        (line, module)
        for line, module in _imported_modules(tree)
        if not _is_public_application_import(module)
    ]


def _application_import_violations(module_path: Path) -> list[tuple[int, str]]:
    return _application_import_violations_from_source(module_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("module_path", _ADMIN_INTERFACE_PY, ids=_relative_id)
def test_admin_interfaces_import_only_public_application_surface(
    module_path: Path,
) -> None:
    violations = _application_import_violations(module_path)
    assert violations == [], (
        f"{module_path.relative_to(_REPO_ROOT)}: forbidden application imports: "
        + ", ".join(f"L{line} {module}" for line, module in violations)
    )


def test_importlinter_forbids_master_data_hydrate_internal_from_interfaces() -> None:
    source = "from src.application.master_data.hydrate import hydrate_provider_from_master_data\n"
    violations = _application_import_violations_from_source(source)
    assert violations == [(1, "src.application.master_data.hydrate")]
