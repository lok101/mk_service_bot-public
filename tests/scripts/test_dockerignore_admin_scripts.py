from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"


def _dockerignore_lines() -> list[str]:
    return [
        line.strip()
        for line in _DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_dockerignore_unignores_settlement_admin_entrypoint() -> None:
    lines = _dockerignore_lines()
    assert "scripts/*" in lines
    assert "!scripts/settlement_admin.py" in lines


def test_dockerignore_unignores_settlement_admin_lib_package() -> None:
    """Shim imports scripts.settlement_admin_lib; package must ship in the image."""
    lines = _dockerignore_lines()
    assert "!scripts/settlement_admin_lib/" in lines or "!scripts/settlement_admin_lib" in lines
    assert "!scripts/settlement_admin_lib/**" in lines


def test_dockerignore_unignores_snack_loading_admin() -> None:
    lines = _dockerignore_lines()
    assert "!scripts/snack_loading_admin.py" in lines


def test_dockerignore_unignores_migrate_warehouse_form_baseline_admin() -> None:
    lines = _dockerignore_lines()
    assert "!scripts/migrate_warehouse_form_baseline_admin.py" in lines


def test_dockerignore_unignores_machine_pnl_admin() -> None:
    lines = _dockerignore_lines()
    assert "!scripts/machine_pnl_admin.py" in lines


def test_dockerignore_does_not_unignore_pre_loading_migrate_admin() -> None:
    lines = _dockerignore_lines()
    assert "!scripts/pre_loading_migrate_admin.py" not in lines
