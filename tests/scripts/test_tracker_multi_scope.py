from __future__ import annotations

from pathlib import Path

import pytest
from scripts.tracker_issue_lib import cli as tracker_cli


def _run(root: Path, *argv: str) -> tuple[int, dict[str, object]]:
    code, payload = tracker_cli.main(["--tracker-root", str(root), *argv])
    assert isinstance(payload, dict)
    return code, payload


def _write_board(tmp_path: Path) -> Path:
    board = tmp_path / "agent_board"
    (board / "vault" / "mk" / "ISSUES").mkdir(parents=True)
    (board / "vault" / "other" / "ISSUES").mkdir(parents=True)
    (board / "projects.yaml").write_text(
        """
projects:
  mk:
    title: MK
    prefix: ISS
    path: vault/mk
    domains: [platform]
  other:
    title: Other
    prefix: OTH
    path: vault/other
    domains: [platform]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return board


def test_multi_scope_create_list_all(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    code, created = _run(board, "--scope", "mk", "save", "--title", "Mk card", "--status", "open")
    assert code == 0
    assert created["id"] == "ISS-001"
    assert created["issue"]["scope"] == "mk"  # type: ignore[index]

    code, other = _run(board, "--scope", "other", "save", "--title", "Oth card", "--status", "open")
    assert code == 0
    assert other["id"] == "OTH-001"
    assert other["issue"]["scope"] == "other"  # type: ignore[index]

    code, listed = _run(board, "--all", "list")
    assert code == 0
    ids = {item["id"] for item in listed["issues"]}  # type: ignore[index]
    assert ids == {"ISS-001", "OTH-001"}


def test_multi_scope_domain_uses_scope_allowlist(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    text = (board / "projects.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "path: vault/other\n    domains: [platform]",
        "path: vault/other\n    domains: [corpus, runtime]",
    )
    (board / "projects.yaml").write_text(text, encoding="utf-8")

    code, created = _run(
        board,
        "--scope",
        "other",
        "save",
        "--title",
        "Kernel card",
        "--status",
        "backlog",
        "--domain",
        "corpus",
    )
    assert code == 0
    assert created["issue"]["domain"] == "corpus"  # type: ignore[index]

    code, bad = _run(
        board,
        "--scope",
        "other",
        "save",
        "--title",
        "Wrong domain",
        "--domain",
        "platform",
    )
    assert code == 1
    assert bad["code"] == "invalid_args"

    code, listed = _run(board, "--all", "list")
    assert code == 0
    ids = {item["id"] for item in listed["issues"]}  # type: ignore[index]
    assert ids == {"OTH-001"}


def test_multi_scope_mutate_requires_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACKER_PROJECT", raising=False)
    board = _write_board(tmp_path)
    code, payload = _run(board, "save", "--title", "No scope", "--status", "open")
    assert code == 1
    assert payload["ok"] is False
    assert payload["code"] == "invalid_args"


def test_multi_scope_all_forbids_mutate(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    code, payload = _run(board, "--all", "save", "--title", "Nope", "--status", "open")
    assert code == 1
    assert payload["code"] == "invalid_args"


def test_multi_scope_normalize_backfills_scope(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    code, created = _run(board, "--scope", "mk", "save", "--title", "Backfill", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    path = board / "vault" / "mk" / "ISSUES" / f"{issue_id}.md"
    text = path.read_text(encoding="utf-8").replace("scope: mk\n", "scope: null\n")
    path.write_text(text, encoding="utf-8")
    code, norm = _run(board, "--scope", "mk", "normalize")
    assert code == 0
    assert norm["rewritten"] == 1
    code, got = _run(board, "--scope", "mk", "get", issue_id)
    assert code == 0
    assert got["issue"]["scope"] == "mk"  # type: ignore[index]
