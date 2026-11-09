from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_adr_number_lib.cli import main


def _touch_adr(root: Path, number: int) -> None:
    directory = root / "docs" / "adr"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{number:04d}-example.md").write_text(
        f"# ADR-{number:04d}: example\n",
        encoding="utf-8",
    )


def test_cli_reserve_json_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    code = main(
        [
            "--git-common-dir",
            str(common),
            "reserve",
            "--catalog",
            "adr",
            "--slug",
            "demo",
            "--job-id",
            "job-abc",
            "--worktree-root",
            str(wt),
            "--head-max",
            "0",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog"] == "adr"
    assert payload["number"] == 1
    assert payload["padded"] == "0001"
    assert payload["reservation_id"] == "adr-0001"
    assert "path_hint" in payload
    assert payload["path_hint"].endswith("0001-demo.md")


def test_cli_status_reports_water(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    assert (
        main(
            [
                "--git-common-dir",
                str(common),
                "reserve",
                "--catalog",
                "adr",
                "--worktree-root",
                str(wt),
                "--head-max",
                "0",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--git-common-dir", str(common), "status", "--catalog", "adr"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adr"] == 1


def test_cli_sync_floor_raises_water_without_issuing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _touch_adr(wt, 20)
    code = main(
        [
            "--git-common-dir",
            str(common),
            "sync-floor",
            "--worktree-root",
            str(wt),
            "--head-max-adr",
            "0",
            "--head-max-ui-adr",
            "0",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adr"] == 20
    assert main(["--git-common-dir", str(common), "status"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["adr"] == 20


def test_cli_unknown_catalog_exit_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = tmp_path / "common"
    common.mkdir()
    code = main(
        [
            "--git-common-dir",
            str(common),
            "reserve",
            "--catalog",
            "nope",
            "--worktree-root",
            str(tmp_path),
            "--head-max",
            "0",
        ]
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "catalog" in err.lower() or "invalid" in err.lower() or "choice" in err.lower()


def test_cli_status_empty_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = tmp_path / "common"
    common.mkdir()
    assert main(["--git-common-dir", str(common), "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adr"] == 0
    assert payload["ui-adr"] == 0
    assert payload["skill-adr"] == 0


def test_cli_reserve_skill_adr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    code = main(
        [
            "--git-common-dir",
            str(common),
            "reserve",
            "--catalog",
            "skill-adr",
            "--slug",
            "first",
            "--worktree-root",
            str(wt),
            "--head-max",
            "0",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog"] == "skill-adr"
    assert payload["number"] == 1
    assert payload["path_hint"].replace("\\", "/").endswith("docs/skill-adr/0001-first.md")
