from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CHECK_SH = _ROOT / "scripts" / "check.sh"
_CHECK_PS1 = _ROOT / "scripts" / "check.ps1"
_FORMAL_SH = _ROOT / "scripts" / "formal-check.sh"
_FORMAL_PS1 = _ROOT / "scripts" / "formal-check.ps1"
_LINT = "scripts/lint_invariants.py"
_MODELS = "scripts/check_formal_models.py"
_LINT_COMMAND = "uv run python scripts/lint_invariants.py"
_MODELS_COMMAND = "uv run python scripts/check_formal_models.py"


def test_normal_shell_and_powershell_checks_run_invariant_lint_before_pytest() -> None:
    shell = _CHECK_SH.read_text(encoding="utf-8")
    powershell = _CHECK_PS1.read_text(encoding="utf-8")

    assert _LINT in shell
    assert _LINT in powershell
    assert shell.index(_LINT) < shell.index("pytest -q")
    assert powershell.index(_LINT) < powershell.index("'pytest', '-q'")


def test_normal_checks_do_not_require_java_or_tlc() -> None:
    shell = _CHECK_SH.read_text(encoding="utf-8")
    powershell = _CHECK_PS1.read_text(encoding="utf-8")
    for text in (shell, powershell):
        lowered = text.lower()
        assert "java" not in lowered
        assert "tlc" not in lowered
        assert _MODELS not in text
        assert "formal-check" not in text


def test_formal_shell_and_powershell_checks_run_registry_then_models() -> None:
    shell = _FORMAL_SH.read_text(encoding="utf-8")
    powershell = _FORMAL_PS1.read_text(encoding="utf-8")

    for text in (shell, powershell):
        assert _LINT in text
        assert _MODELS in text
        assert text.index(_LINT) < text.index(_MODELS)


def test_formal_wrappers_delegate_to_same_python_runner() -> None:
    shell = _FORMAL_SH.read_text(encoding="utf-8")
    powershell = _FORMAL_PS1.read_text(encoding="utf-8")

    assert _LINT_COMMAND in shell
    assert _MODELS_COMMAND in shell
    assert "python" in powershell
    assert _LINT in powershell
    assert _MODELS in powershell
    assert "$LASTEXITCODE" in powershell
    assert "Set-StrictMode" in powershell
    assert "$ErrorActionPreference" in powershell
    assert "Set-Location" in powershell
