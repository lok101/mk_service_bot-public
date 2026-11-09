from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.paths import (
    PathPolicyError,
    assert_contract_permissions,
    normalize_contract_path,
    path_is_allowed,
    resolve_workspace_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src\\domain\\item.py", "src/domain/item.py"),
        ("src/domain/item.py", "src/domain/item.py"),
        ("tests\\scripts\\", "tests/scripts/"),
    ],
)
def test_windows_and_posix_paths_normalize_identically(
    tmp_path: Path, raw: str, expected: str
) -> None:
    assert normalize_contract_path(raw, workspace=tmp_path) == expected


@pytest.mark.parametrize(
    "raw",
    ["../secret", "/etc/passwd", "C:\\secret.txt", "src/**", "src/./item.py"],
)
def test_path_policy_rejects_traversal_absolute_and_glob_paths(tmp_path: Path, raw: str) -> None:
    with pytest.raises(PathPolicyError, match="AGT001"):
        normalize_contract_path(raw, workspace=tmp_path)


def test_directory_allowlist_does_not_match_neighbor_prefix() -> None:
    assert path_is_allowed("src/domain/item.py", ("src/domain/",))
    assert not path_is_allowed("src/domain_evil/item.py", ("src/domain/",))


def test_path_policy_accepts_unicode_repository_relative_path(
    tmp_path: Path,
) -> None:
    assert normalize_contract_path("docs/планы/файл.md", workspace=tmp_path) == "docs/планы/файл.md"


def test_path_policy_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(PathPolicyError, match="AGT005"):
        resolve_workspace_path(tmp_path, "escape.txt")


@pytest.mark.parametrize(
    "path",
    [
        ".cursor/hooks.json",
        ".cursor/agent-contract/schema.json",
        ".cursor/agent-contract/contracts/aec-example.json",
        "scripts/agent_contract_guard.py",
        "scripts/agent_contract_guard_lib/paths.py",
        ".github/workflows/check.yml",
        ".github/CODEOWNERS",
        ".github/workflows/e2e-flows.yml",
    ],
)
def test_builtin_guard_policy_cannot_be_allowlisted(path: str) -> None:
    with pytest.raises(PathPolicyError, match="AGT005"):
        assert_contract_permissions(
            write_allowlist=(path,),
            protected_paths=(),
        )
