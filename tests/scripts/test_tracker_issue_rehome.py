from __future__ import annotations

from pathlib import Path

from scripts.tracker_issue_lib import cli as tracker_cli


def _run(root: Path, *argv: str) -> tuple[int, dict[str, object]]:
    code, payload = tracker_cli.main(["--tracker-root", str(root), *argv])
    assert isinstance(payload, dict)
    return code, payload


def _write_board(tmp_path: Path) -> Path:
    board = tmp_path / "agent_board"
    (board / "vault" / "mk" / "ISSUES").mkdir(parents=True)
    (board / "vault" / "agent" / "ISSUES").mkdir(parents=True)
    (board / "projects.yaml").write_text(
        """
projects:
  mk:
    title: MK
    prefix: ISS
    path: vault/mk
    domains: [platform]
  agent:
    title: Agent
    prefix: AGT
    path: vault/agent
    domains: [runtime, conformance, cutover]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return board


def test_rehome_mk_to_agent_and_legacy_get(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    code, created = _run(
        board,
        "--scope",
        "mk",
        "save",
        "--title",
        "Cursor handoff",
        "--status",
        "backlog",
        "--domain",
        "platform",
    )
    assert code == 0
    source_id = str(created["id"])
    assert source_id == "ISS-001"

    code, moved = _run(
        board,
        "--scope",
        "mk",
        "rehome",
        source_id,
        "--to-scope",
        "agent",
        "--target-domain",
        "runtime",
    )
    assert code == 0
    target_id = str(moved["target_id"])
    assert target_id == "AGT-001"

    code, stub = _run(board, "--scope", "mk", "get", source_id)
    assert code == 0
    assert stub["issue"]["status"] == "cancelled"  # type: ignore[index]
    assert stub["issue"]["legacy_id"] == target_id  # type: ignore[index]

    code, canonical = _run(board, "get", "--legacy", source_id)
    assert code == 0
    assert canonical["issue"]["id"] == target_id  # type: ignore[index]
    assert canonical["issue"]["legacy_id"] == source_id  # type: ignore[index]


def test_rehome_busy_when_claimed(tmp_path: Path) -> None:
    board = _write_board(tmp_path)
    code, created = _run(board, "--scope", "mk", "save", "--title", "Held", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert _run(board, "--scope", "mk", "claim", issue_id, "--by", "agent/x")[0] == 0

    code, payload = _run(
        board,
        "--scope",
        "mk",
        "rehome",
        issue_id,
        "--to-scope",
        "agent",
        "--target-domain",
        "runtime",
    )
    assert code == 1
    assert payload["code"] == "busy"
