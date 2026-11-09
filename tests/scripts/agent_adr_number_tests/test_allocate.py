from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from scripts.agent_adr_number_lib.allocate import reserve, status, sync_floor
from scripts.agent_adr_number_lib.paths import high_water_path, reservations_dir
from scripts.agent_adr_number_lib.store import StoreCorruptError, load_high_water


def _touch_adr(root: Path, catalog: str, number: int, slug: str = "example") -> Path:
    rel = Path("docs") / ("ui-adr" if catalog == "ui-adr" else "adr")
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{number:04d}-{slug}.md"
    prefix = "UI-ADR" if catalog == "ui-adr" else "ADR"
    path.write_text(f"# {prefix}-{number:04d}: x\n", encoding="utf-8")
    return path


def test_floor_uses_max_of_water_files_head(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    wt_a.mkdir()
    wt_b.mkdir()
    _touch_adr(wt_a, "adr", 10)
    _touch_adr(wt_b, "adr", 12)
    high_water_path(common).parent.mkdir(parents=True, exist_ok=True)
    high_water_path(common).write_text(
        json.dumps({"adr": 11, "ui-adr": 0, "updated_at": "2026-10-13T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    result = reserve(
        common,
        "adr",
        worktree_roots=(wt_a, wt_b),
        head_max=15,
        slug="from-floor",
    )
    assert result.number == 16
    assert result.padded == "0016"
    assert result.catalog == "adr"
    assert result.path_hint.endswith("0016-from-floor.md")


def test_empty_water_defaults_to_zero(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    result = reserve(common, "adr", worktree_roots=(wt,), head_max=0)
    assert result.number == 1
    water = load_high_water(common)
    assert water["adr"] == 1
    assert water["ui-adr"] == 0
    assert water["skill-adr"] == 0


def test_gap_after_reserve_without_file(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    first = reserve(common, "adr", worktree_roots=(wt,), head_max=5, slug="gone")
    assert first.number == 6
    # No ADR file created — gap is intentional.
    second = reserve(common, "adr", worktree_roots=(wt,), head_max=5)
    assert second.number == 7


def test_skill_adr_series_stays_independent(tmp_path: Path) -> None:
    # self-check: skill-adr series stays independent
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _touch_adr(wt, "adr", 3)
    adr = reserve(common, "adr", worktree_roots=(wt,), head_max=3)
    skill = reserve(
        common,
        "skill-adr",
        worktree_roots=(wt,),
        head_max=0,
        slug="first",
    )
    assert adr.number == 4
    assert skill.number == 1
    assert skill.path_hint.replace("\\", "/").endswith("docs/skill-adr/0001-first.md")
    water = load_high_water(common)
    assert water["adr"] == 4
    assert water["ui-adr"] == 0
    assert water["skill-adr"] == 1


def test_missing_skill_adr_key_reads_as_zero(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    high_water_path(common).parent.mkdir(parents=True, exist_ok=True)
    high_water_path(common).write_text(
        json.dumps({"adr": 8, "ui-adr": 2, "updated_at": "2026-10-13T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    wt = tmp_path / "wt"
    wt.mkdir()
    result = reserve(common, "skill-adr", worktree_roots=(wt,), head_max=0)
    assert result.number == 1
    water = load_high_water(common)
    assert water["adr"] == 8
    assert water["ui-adr"] == 2
    assert water["skill-adr"] == 1


def test_adr_and_ui_adr_series_independent(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    adr = reserve(common, "adr", worktree_roots=(wt,), head_max=0)
    ui = reserve(common, "ui-adr", worktree_roots=(wt,), head_max=0)
    assert adr.number == 1
    assert ui.number == 1
    water = load_high_water(common)
    assert water["adr"] == 1
    assert water["ui-adr"] == 1


def test_parallel_reserve_distinct_numbers(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()

    def _one(_: int) -> int:
        return reserve(common, "adr", worktree_roots=(wt,), head_max=0).number

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(_one, range(8)))
    assert len(numbers) == len(set(numbers))
    assert sorted(numbers) == list(range(1, 9))


def test_unknown_catalog_fails(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    with pytest.raises(ValueError, match="catalog"):
        reserve(common, "other", worktree_roots=(), head_max=0)
    assert not high_water_path(common).exists()


def test_corrupt_high_water_fail_closed(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    path = high_water_path(common)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        reserve(common, "adr", worktree_roots=(), head_max=0)
    assert path.read_text(encoding="utf-8") == "{not-json"


def test_sync_floor_raises_water_without_issuing(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _touch_adr(wt, "adr", 42)
    res_dir = reservations_dir(common)
    before = list(res_dir.glob("*.json")) if res_dir.exists() else []
    water = sync_floor(
        common,
        worktree_roots=(wt,),
        head_max_by_catalog={"adr": 40, "ui-adr": 0},
    )
    assert water["adr"] == 42
    after = list(res_dir.glob("*.json")) if res_dir.exists() else []
    assert after == before
    status_payload = status(common, catalog="adr")
    assert status_payload["adr"] == 42


def test_status_empty_store(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    payload = status(common)
    assert payload["adr"] == 0
    assert payload["ui-adr"] == 0
