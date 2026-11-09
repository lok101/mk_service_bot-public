from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = "scripts/lint_architecture_docs.py"
_CUTOFF = "2026-09-15"


def test_check_wrappers_run_architecture_docs_lint_with_same_cutoff() -> None:
    shell = (_ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    powershell = (_ROOT / "scripts" / "check.ps1").read_text(encoding="utf-8")

    assert shell.count(_SCRIPT) == 1
    assert shell.count(_CUTOFF) == 1
    assert powershell.count(_SCRIPT) == 1
    assert powershell.count(_CUTOFF) == 1
