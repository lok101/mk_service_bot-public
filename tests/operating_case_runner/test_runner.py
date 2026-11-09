from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from operating_cases.report import BreakReport, ClosedReport, InvalidCaseError, format_report_line
from operating_cases.steps import Step, require_valid_steps
from scripts.run_operating_case import execute_case_module


def test_format_closed_report_line() -> None:
    assert format_report_line(ClosedReport()) == "closed"


def test_format_break_report_line_includes_step_and_sources() -> None:
    report = BreakReport(
        step_id="recount",
        sources=("docs/specs/loading.md", "forms"),
        message="item missing from recount",
    )
    assert format_report_line(report) == (
        "break recount docs/specs/loading.md,forms item missing from recount"
    )


def test_require_valid_steps_rejects_empty_case() -> None:
    with pytest.raises(InvalidCaseError, match="no steps"):
        require_valid_steps(())


def test_require_valid_steps_rejects_empty_sources() -> None:
    with pytest.raises(InvalidCaseError, match="no sources"):
        require_valid_steps((Step(step_id="load", sources=()),))


def test_require_valid_steps_accepts_nonempty_sources() -> None:
    require_valid_steps((Step(step_id="load", sources=("loading",)),))


def _install_case_module(tmp_path: Path, module_name: str, source: str) -> None:
    package_root = tmp_path / "_oc_cases"
    package_root.mkdir(exist_ok=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / f"{module_name}.py").write_text(source, encoding="utf-8")
    root = str(tmp_path)
    if root not in sys.path:
        sys.path.insert(0, root)
    importlib.invalidate_caches()
    full_name = f"_oc_cases.{module_name}"
    sys.modules.pop(full_name, None)
    sys.modules.pop("_oc_cases", None)


def test_runner_closed_report_exits_0(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "closed_case",
        (
            "from operating_cases.report import ClosedReport\n\n"
            "def run():\n"
            "    return ClosedReport()\n"
        ),
    )
    code, line = execute_case_module("_oc_cases.closed_case")
    assert code == 0
    assert line == "closed"


def test_runner_break_report_exits_1_with_step_and_sources(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "break_case",
        (
            "from operating_cases.report import BreakReport\n\n"
            "def run():\n"
            "    return BreakReport(\n"
            '        step_id="recount",\n'
            '        sources=("loading", "forms"),\n'
            '        message="item missing from recount",\n'
            "    )\n"
        ),
    )
    code, line = execute_case_module("_oc_cases.break_case")
    assert code == 1
    assert line == "break recount loading,forms item missing from recount"


def test_runner_no_steps_exits_2_with_invalid_case(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "no_steps_case",
        (
            "from operating_cases.steps import require_valid_steps\n\n"
            "def run():\n"
            "    require_valid_steps(())\n"
            "    return None\n"
        ),
    )
    code, line = execute_case_module("_oc_cases.no_steps_case")
    assert code == 2
    assert line.startswith("invalid case")


def test_runner_empty_sources_exits_2_with_invalid_case(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "empty_sources_case",
        (
            "from operating_cases.steps import Step, require_valid_steps\n\n"
            "def run():\n"
            '    require_valid_steps((Step(step_id="load", sources=()),))\n'
            "    return None\n"
        ),
    )
    code, line = execute_case_module("_oc_cases.empty_sources_case")
    assert code == 2
    assert line.startswith("invalid case")


def test_runner_raised_exception_exits_2_with_invalid_case(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "boom_case",
        'def run():\n    raise RuntimeError("boom")\n',
    )
    code, line = execute_case_module("_oc_cases.boom_case")
    assert code == 2
    assert line.startswith("invalid case")


def test_cli_help_exits_0() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "run_operating_case.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "No module named" not in completed.stderr
    assert "operating case" in completed.stdout.lower()


def test_closed_handoff_fixture_exits_0() -> None:
    code, line = execute_case_module("operating_cases.fixtures.closed_handoff")
    assert code == 0
    assert line == "closed"


def test_seam_break_fixture_exits_1_with_step_and_sources() -> None:
    code, line = execute_case_module("operating_cases.fixtures.seam_break")
    assert code == 1
    assert line.startswith("break recount ")
    assert "loading" in line
    assert "forms" in line


def test_seam_break_does_not_run_tail_step() -> None:
    # Импорт модуля и вызов run() напрямую: модуль выставляет флаг хвоста.
    import importlib

    mod = importlib.import_module("operating_cases.fixtures.seam_break")
    mod.TAIL_RAN = False
    report = mod.run()
    assert report.status == "break"
    assert report.step_id == "recount"
    assert set(report.sources) == {"loading", "forms"}
    assert mod.TAIL_RAN is False


def _python_sources_under(*relative: str) -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    paths: list[Path] = []
    for rel in relative:
        base = root / rel
        if base.is_file():
            paths.append(base)
        else:
            paths.extend(sorted(base.rglob("*.py")))
    return paths


def test_operating_case_sources_do_not_import_src() -> None:
    forbidden = ("from src", "import src")
    for path in _python_sources_under("operating_cases", "scripts/run_operating_case.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path}: contains {token!r}"


def test_invariant_registry_has_no_operating_case_entries() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "verification" / "invariants.toml").read_text(encoding="utf-8")
    assert "operating_case" not in text
    assert "operating-case" not in text


def test_cli_closed_report_prints_one_line_and_exits_0(tmp_path: Path) -> None:
    _install_case_module(
        tmp_path,
        "closed_case",
        (
            "from operating_cases.report import ClosedReport\n\n"
            "def run():\n"
            "    return ClosedReport()\n"
        ),
    )
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "run_operating_case.py"),
            "_oc_cases.closed_case",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == ["closed"]
