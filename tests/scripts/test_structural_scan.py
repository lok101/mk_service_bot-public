from __future__ import annotations

from pathlib import Path

from scripts.structural_scan import run_structural_scan


def test_structural_scan_happy_both_commands(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: tuple[str, ...], cwd: Path) -> int:
        calls.append((tuple(argv), cwd))
        return 0

    assert run_structural_scan(tmp_path, runner=runner) == 0
    assert calls == [
        (("ast-grep", "scan"), tmp_path),
        (("ast-grep", "test", "--skip-snapshot-tests"), tmp_path),
    ]


def test_structural_scan_edge_stops_after_scan_failure(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], cwd: Path) -> int:
        del cwd
        calls.append(tuple(argv))
        return 2

    assert run_structural_scan(tmp_path, runner=runner) == 2
    assert calls == [("ast-grep", "scan")]


def test_structural_scan_error_missing_cli(tmp_path: Path) -> None:
    from scripts.structural_scan import default_structural_runner

    code = default_structural_runner(("sg-not-installed-xyz",), tmp_path)
    assert code == 127
