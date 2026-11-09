from __future__ import annotations

from pathlib import Path

from scripts.agent_lane_lib.dirty_gate import list_gated_dirty


def test_dirty_gate_ok_with_only_secret_and_env(tmp_path: Path) -> None:
    leftovers = list_gated_dirty(
        tmp_path,
        dirty_paths=[
            "docs/specs/.env.local",
            "tasks/secret-note.md",
            "docs/plans/foo.secret.bak",
            "src/unrelated.py",
        ],
    )
    assert leftovers == []


def test_dirty_gate_lists_leftover_under_docs_specs(tmp_path: Path) -> None:
    leftovers = list_gated_dirty(
        tmp_path,
        dirty_paths=[
            "docs/specs/2026-10-09-x-design.md",
            "docs/ui-demos/a/index.html",
            "README.md",
        ],
    )
    assert leftovers == [
        "docs/specs/2026-10-09-x-design.md",
        "docs/ui-demos/a/index.html",
    ]
