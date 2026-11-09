from __future__ import annotations

from pathlib import Path

from scripts.agent_recovery_permit_lib.preconditions import (
    evaluate_remove_unregistered_lane_residue,
)


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    primary = tmp_path / "mk_service_bot"
    primary.mkdir()
    wt_root = tmp_path / "mk_service_bot-wt"
    wt_root.mkdir()
    target = wt_root / "lane-slug"
    target.mkdir()
    return primary, wt_root, target


def test_residue_preconditions_pass_for_unregistered_exact_path(tmp_path: Path) -> None:
    primary, wt_root, target = _layout(tmp_path)
    porcelain = f"worktree {primary}\nHEAD abc\nbranch refs/heads/main\n\n"
    command = f"Remove-Item -LiteralPath {target.resolve()}"
    result = evaluate_remove_unregistered_lane_residue(
        primary_repo=primary,
        worktrees_root=wt_root,
        slug="lane-slug",
        target=target,
        worktree_list_porcelain=porcelain,
        branch_merged=True,
        command=command,
        has_tracked_content=False,
    )
    assert result.ok
    assert result.reason == "ok"


def test_residue_rejects_registered_worktree(tmp_path: Path) -> None:
    primary, wt_root, target = _layout(tmp_path)
    porcelain = (
        f"worktree {primary}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {target.resolve()}\nHEAD def\nbranch refs/heads/agent/lane-slug\n\n"
    )
    result = evaluate_remove_unregistered_lane_residue(
        primary_repo=primary,
        worktrees_root=wt_root,
        slug="lane-slug",
        target=target,
        worktree_list_porcelain=porcelain,
        branch_merged=True,
        command=f"Remove-Item -LiteralPath {target.resolve()}",
        has_tracked_content=False,
    )
    assert not result.ok
    assert result.reason == "target_registered_worktree"


def test_residue_rejects_wildcard_or_parent_escape(tmp_path: Path) -> None:
    primary, wt_root, target = _layout(tmp_path)
    porcelain = f"worktree {primary}\nHEAD abc\nbranch refs/heads/main\n\n"
    result = evaluate_remove_unregistered_lane_residue(
        primary_repo=primary,
        worktrees_root=wt_root,
        slug="lane-slug",
        target=target,
        worktree_list_porcelain=porcelain,
        branch_merged=True,
        command=f"Remove-Item -Recurse -Force {wt_root}\\*",
        has_tracked_content=False,
    )
    assert not result.ok
    assert result.reason == "command_not_exact_target_delete"


def test_residue_rejects_symlink_escape(tmp_path: Path) -> None:
    primary, wt_root, _target = _layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = wt_root / "lane-slug"
    # Replace directory with symlink if platform allows; otherwise simulate via
    # has_tracked_content=False and a fake resolve mismatch by using a file path.
    try:
        link.rmdir()
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows without symlink privilege: assert tracked content gate instead.
        link.mkdir(exist_ok=True)
        result = evaluate_remove_unregistered_lane_residue(
            primary_repo=primary,
            worktrees_root=wt_root,
            slug="lane-slug",
            target=link,
            worktree_list_porcelain=f"worktree {primary}\nHEAD abc\n\n",
            branch_merged=True,
            command=f"Remove-Item -LiteralPath {link.resolve()}",
            has_tracked_content=True,
        )
        assert not result.ok
        assert result.reason == "target_has_tracked_content"
        return

    result = evaluate_remove_unregistered_lane_residue(
        primary_repo=primary,
        worktrees_root=wt_root,
        slug="lane-slug",
        target=link,
        worktree_list_porcelain=f"worktree {primary}\nHEAD abc\n\n",
        branch_merged=True,
        command=f"Remove-Item -LiteralPath {link}",
        has_tracked_content=False,
    )
    assert not result.ok
    assert result.reason == "symlink_escape"
