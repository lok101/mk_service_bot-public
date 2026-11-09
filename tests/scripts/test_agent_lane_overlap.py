from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.agent_lane_overlap import run_classify


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_primary_with_lane_differs(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "mk_service_bot"
    primary.mkdir()
    _git(primary, "init")
    _git(primary, "config", "user.email", "lane@example.invalid")
    _git(primary, "config", "user.name", "Lane Test")
    rel = "docs/ui-demos/demo/index.html"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_text("primary-base\n", encoding="utf-8")
    _git(primary, "add", rel)
    _git(primary, "commit", "-m", "base")

    lane_root = primary.parent / "mk_service_bot-wt"
    lane_root.mkdir()
    lane = lane_root / "shelves"
    _git(primary, "worktree", "add", "-b", "agent/shelves", str(lane), "HEAD")
    (lane / rel).write_text("lane-version\n", encoding="utf-8")
    _git(lane, "add", rel)
    _git(lane, "commit", "-m", "lane change")

    # Dirty primary differs from lane tip on the same overlapping path.
    path.write_text("primary-dirty-differs\n", encoding="utf-8")
    return primary, path


def test_overlap_differs_with_cleanup_does_not_wipe(tmp_path: Path) -> None:
    primary, differs_path = _init_primary_with_lane_differs(tmp_path)
    before = differs_path.read_text(encoding="utf-8")

    code = run_classify(primary, slug="shelves", cleanup=True)

    assert code == 1
    assert differs_path.is_file()
    assert differs_path.read_text(encoding="utf-8") == before
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    reports = list((git_common / "agent-process-reports" / "reports").glob("*/*.json"))
    assert any("overlap_differs" in p.read_text(encoding="utf-8") for p in reports)
