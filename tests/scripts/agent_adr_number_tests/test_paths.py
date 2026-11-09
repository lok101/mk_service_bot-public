from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_adr_number_lib.paths import (
    adr_numbers_root,
    allocate_lock_path,
    catalog_docs_relpath,
    high_water_path,
    reservations_dir,
    resolve_git_common_dir,
    validate_catalog,
)


def test_adr_numbers_root_under_git_common_dir(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    root = adr_numbers_root(common)
    assert root == common / "adr-numbers"
    assert high_water_path(common) == root / "high-water.json"
    assert reservations_dir(common) == root / "reservations"
    assert allocate_lock_path(common) == root / "locks" / "allocate.lock"


def test_catalog_docs_relpath() -> None:
    assert catalog_docs_relpath("adr") == Path("docs") / "adr"
    assert catalog_docs_relpath("ui-adr") == Path("docs") / "ui-adr"
    assert catalog_docs_relpath("skill-adr") == Path("docs") / "skill-adr"


def test_validate_catalog_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="catalog"):
        validate_catalog("nope")


def test_resolve_git_common_dir_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "override-common"
    common.mkdir()
    monkeypatch.setenv("AGENT_JOB_GIT_COMMON_DIR", str(common))
    assert resolve_git_common_dir() == common.resolve()


def test_missing_git_common_dir_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_JOB_GIT_COMMON_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="git-common-dir|git common"):
        resolve_git_common_dir(cwd=tmp_path)
