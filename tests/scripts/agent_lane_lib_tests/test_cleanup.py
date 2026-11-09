from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_lane_lib.cleanup import DiffersPresentError, cleanup_identical_paths


def test_cleanup_unlinks_identical_untracked(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    rel = "docs/ui-demos/demo/index.html"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"<html>same</html>")

    cleaned = cleanup_identical_paths(
        primary,
        [(rel, "identical")],
        head_blob_reader=lambda _p: None,
        is_untracked=lambda _p: True,
    )

    assert cleaned == [rel]
    assert not path.exists()


def test_cleanup_restores_identical_tracked_via_python_write(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    rel = "docs/ui-adr/README.md"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"dirty working tree\n")
    head = b"# committed\n"

    cleaned = cleanup_identical_paths(
        primary,
        [(rel, "identical")],
        head_blob_reader={rel: head}.get,
        is_untracked=lambda _p: False,
    )

    assert cleaned == [rel]
    assert path.read_bytes() == head


def test_cleanup_refuses_when_differs_present(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    identical = "docs/ui-demos/ok.html"
    differs = "docs/ui-demos/bad.html"
    for rel, body in ((identical, b"ok"), (differs, b"bad")):
        path = primary / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    with pytest.raises(DiffersPresentError, match="differs") as exc_info:
        cleanup_identical_paths(
            primary,
            [(identical, "identical"), (differs, "differs")],
            head_blob_reader=lambda _p: None,
            is_untracked=lambda _p: True,
        )

    assert differs in str(exc_info.value)
    assert (primary / identical).exists()
    assert (primary / differs).read_bytes() == b"bad"
