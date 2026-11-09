from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.agent_process_apr_lib.residue_delete import (
    ResidueDeleteError,
    exact_residue_delete,
    residue_next_command,
)


def test_exact_residue_delete_clears_readonly_then_removes(tmp_path: Path) -> None:
    target = tmp_path / "residue-lane"
    target.mkdir()
    locked = target / "locked.txt"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IREAD)
    exact_residue_delete(target)
    assert not target.exists()


def test_exact_residue_delete_retries_then_fails_on_persistent_lock(
    tmp_path: Path,
) -> None:
    target = tmp_path / "busy-lane"
    target.mkdir()
    (target / "f.txt").write_text("x", encoding="utf-8")

    def _always_busy(path: Path) -> None:
        raise PermissionError(13, "busy", str(path))

    with (
        patch("scripts.agent_process_apr_lib.residue_delete._rmtree_once", _always_busy),
        pytest.raises(ResidueDeleteError, match="locked|busy|Permission"),
    ):
        exact_residue_delete(target, retries=2, retry_delay_s=0.0)
    assert target.exists()


def test_residue_next_command_is_exact_literal_path(tmp_path: Path) -> None:
    target = (tmp_path / "lane").resolve()
    cmd = residue_next_command(target)
    assert cmd == f'Remove-Item -LiteralPath "{target}"'
    assert "*" not in cmd
    assert "-Force" not in cmd
