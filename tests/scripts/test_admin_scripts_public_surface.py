from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADMIN_SCRIPTS = sorted((_REPO_ROOT / "scripts").glob("*_admin.py"))
_SETTLEMENT_ADMIN_LIB = sorted(
    path
    for path in (_REPO_ROOT / "scripts" / "settlement_admin_lib").rglob("*.py")
    if "__pycache__" not in path.parts
)
_FORBIDDEN_SETTLEMENT_ADMIN_LIB_MODULES = frozenset(
    {
        "src.application.technician_settlement.draft",
        "src.application.technician_settlement.draft_ports",
    }
)


def _is_allowed_application_import(module: str | None) -> bool:
    if module is None or not module.startswith("src.application."):
        return True
    parts = module.split(".")
    if len(parts) == 3:
        return True
    if len(parts) == 4:
        submodule = parts[3]
        return submodule == "ports" or submodule.endswith("_ports")
    return False


def _is_allowed_settlement_admin_lib_import(module: str | None) -> bool:
    if module in _FORBIDDEN_SETTLEMENT_ADMIN_LIB_MODULES:
        return False
    return _is_allowed_application_import(module)


def _application_modules_from_node(node: ast.AST) -> list[tuple[int, str]]:
    if isinstance(node, ast.ImportFrom):
        if node.module is None:
            return []
        return [(node.lineno, node.module)]
    if isinstance(node, ast.Import):
        return [(node.lineno, alias.name) for alias in node.names]
    return []


def _application_import_violations_from_source(
    source: str,
    *,
    filename: str = "<memory>",
    is_allowed: Callable[[str | None], bool] | None = None,
) -> list[tuple[int, str]]:
    allow = _is_allowed_application_import if is_allowed is None else is_allowed
    tree = ast.parse(source, filename=filename)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        for lineno, module in _application_modules_from_node(node):
            if module.startswith("src.application.") and not allow(module):
                violations.append((lineno, module))
    return violations


def _application_import_violations(path: Path) -> list[tuple[int, str]]:
    return _application_import_violations_from_source(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def _settlement_admin_lib_import_violations(path: Path) -> list[tuple[int, str]]:
    return _application_import_violations_from_source(
        path.read_text(encoding="utf-8"),
        filename=str(path),
        is_allowed=_is_allowed_settlement_admin_lib_import,
    )


@pytest.mark.parametrize("script_path", _ADMIN_SCRIPTS, ids=lambda path: path.name)
def test_admin_script_imports_only_public_application_surface(
    script_path: Path,
) -> None:
    violations = _application_import_violations(script_path)

    assert violations == [], f"{script_path.name}: forbidden application imports: " + ", ".join(
        f"L{line} {module}" for line, module in violations
    )


def test_admin_script_policy_discovers_expected_scripts() -> None:
    discovered = {path.name for path in _ADMIN_SCRIPTS}
    assert discovered >= {
        "bom_admin.py",
        "maintenance_cooldown_admin.py",
        "matrix_admin.py",
        "outbox_admin.py",
        "settlement_admin.py",
        "snack_loading_admin.py",
    }
    assert "pre_loading_migrate_admin.py" not in discovered


def test_admin_script_policy_rejects_absolute_application_import() -> None:
    violations = _application_import_violations_from_source(
        "import src.application.technician_settlement.preview_all_reconciliations\n"
    )

    assert violations == [
        (1, "src.application.technician_settlement.preview_all_reconciliations"),
    ]


def test_settlement_admin_lib_policy_rejects_draft_and_draft_ports() -> None:
    source = (
        "from src.application.technician_settlement.draft import DraftKind\n"
        "from src.application.technician_settlement.draft_ports import "
        "ReconciliationDraftStore\n"
        "from src.application.technician_settlement import DraftKind as BarrelDraftKind\n"
    )

    violations = _application_import_violations_from_source(
        source,
        is_allowed=_is_allowed_settlement_admin_lib_import,
    )

    assert violations == [
        (1, "src.application.technician_settlement.draft"),
        (2, "src.application.technician_settlement.draft_ports"),
    ]


@pytest.mark.parametrize(
    "module_path",
    _SETTLEMENT_ADMIN_LIB,
    ids=lambda path: str(path.relative_to(_REPO_ROOT / "scripts")),
)
def test_settlement_admin_lib_imports_only_public_application_surface(
    module_path: Path,
) -> None:
    violations = _settlement_admin_lib_import_violations(module_path)

    assert violations == [], (
        f"{module_path.relative_to(_REPO_ROOT)}: forbidden application imports: "
        + ", ".join(f"L{line} {module}" for line, module in violations)
    )
