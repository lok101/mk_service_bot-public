from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.tracker_issue_lib import cli as tracker_cli
from scripts.tracker_issue_lib.import_linear import map_status
from scripts.tracker_issue_lib.models import Issue
from scripts.tracker_issue_lib.store import issue_path, read_issue, write_issue_atomic
from scripts.tracker_issue_lib.time_display import normalize_closed_at


def _run(root: Path, *argv: str) -> tuple[int, dict[str, object]]:
    code, payload = tracker_cli.main(["--tracker-root", str(root), *argv])
    assert isinstance(payload, dict)
    return code, payload


def test_normalize_closed_at_local_sortable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_DISPLAY_TIMEZONE", "Asia/Yekaterinburg")
    assert normalize_closed_at("2026-10-21T07:42:26+00:00") == "2026.10.21 12:42"
    assert normalize_closed_at("2026-10-21T08:00:00+00:00") == "2026.10.21 13:00"
    assert "2026.10.21 12:42" < "2026.10.22 09:00"


def test_tracker_issue_create_claim_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_DISPLAY_TIMEZONE", "Asia/Yekaterinburg")
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Gap in queue", "--status", "open")
    assert code == 0
    assert created["ok"] is True
    assert created["created"] is True
    issue_id = created["id"]
    assert isinstance(issue_id, str)
    assert issue_id.startswith("ISS-")

    code, claimed = _run(root, "claim", issue_id, "--by", "agent/demo")
    assert code == 0
    assert claimed["ok"] is True
    assert claimed["status"] == "open"
    assert claimed["claimed_by"] == "agent/demo"

    code, done = _run(root, "done", issue_id, "--by", "agent/demo", "--note", "verified")
    assert code == 0
    assert done["ok"] is True
    code, got = _run(root, "get", issue_id)
    assert code == 0
    issue = got["issue"]
    assert isinstance(issue, dict)
    assert issue["status"] == "done"
    assert issue["claimed_by"] is None
    assert "Closed" in str(issue.get("body", ""))
    closed_at = issue.get("closed_at")
    assert isinstance(closed_at, str) and closed_at
    assert f"- at: {closed_at}" in str(issue.get("body", ""))
    on_disk = issue_path(root, issue_id).read_text(encoding="utf-8")
    assert f"closed_at: {json.dumps(closed_at)}" in on_disk
    assert closed_at[4] == "." and closed_at[7] == "."
    assert "closed_at_label" not in on_disk


def test_tracker_issue_closed_at_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Preserve", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert _run(root, "claim", issue_id, "--by", "agent/demo")[0] == 0
    assert _run(root, "done", issue_id, "--by", "agent/demo")[0] == 0
    code, got = _run(root, "get", issue_id)
    assert code == 0
    closed_at = got["issue"]["closed_at"]  # type: ignore[index]
    assert isinstance(closed_at, str)
    # save cannot reopen done; rewrite via store round-trip
    issue = read_issue(root, issue_id)
    assert issue.closed_at == closed_at
    write_issue_atomic(root, issue)
    again = read_issue(root, issue_id)
    assert again.closed_at == closed_at
    code, got2 = _run(root, "get", issue_id)
    assert got2["issue"]["closed_at"] == closed_at  # type: ignore[index]


def test_tracker_issue_closed_at_legacy_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_DISPLAY_TIMEZONE", "Asia/Yekaterinburg")
    root = tmp_path / "queue"
    root.mkdir()
    (root / "ISSUES").mkdir()
    stamp = "2026-10-20T12:00:00+00:00"
    expected = "2026.10.20 17:00"
    legacy = Issue(
        id="ISS-9",
        title="Old done",
        status="done",
        body=f"## Closed\n- by: agent/x\n- at: {stamp}\n- note: ok\n- commit:\n",
        closed_at=None,
    )
    write_issue_atomic(root, legacy)
    # Strip closed_at from frontmatter if render already emitted it.
    path = issue_path(root, "ISS-9")
    raw = path.read_text(encoding="utf-8")
    raw = "\n".join(line for line in raw.splitlines() if not line.startswith("closed_at:"))
    if not raw.endswith("\n"):
        raw += "\n"
    path.write_text(raw, encoding="utf-8")

    issue = read_issue(root, "ISS-9")
    assert issue.closed_at == expected
    write_issue_atomic(root, issue)
    rewritten = path.read_text(encoding="utf-8")
    assert f"closed_at: {json.dumps(expected)}" in rewritten


def test_tracker_issue_claim_keeps_status(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Horizon", "--status", "backlog")
    assert code == 0
    issue_id = str(created["id"])
    code, claimed = _run(root, "claim", issue_id, "--by", "agent/demo")
    assert code == 0
    assert claimed["status"] == "backlog"
    assert claimed["claimed_by"] == "agent/demo"
    code, got = _run(root, "get", issue_id)
    assert got["issue"]["status"] == "backlog"  # type: ignore[index]


def test_tracker_issue_save_rejects_done_status(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "X", "--status", "backlog")
    assert code == 0
    issue_id = str(created["id"])
    code, payload = _run(root, "save", "--id", issue_id, "--status", "done")
    assert code != 0
    assert payload["ok"] is False
    assert payload["code"] == "invalid_transition"


def test_tracker_issue_cancel_from_backlog(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "No need", "--status", "backlog")
    assert code == 0
    issue_id = str(created["id"])
    code, cancelled = _run(
        root,
        "cancel",
        issue_id,
        "--by",
        "agent/demo",
        "--reason",
        "no grouping need",
    )
    assert code == 0
    assert cancelled["status"] == "cancelled"
    issue = cancelled["issue"]
    assert isinstance(issue, dict)
    assert issue["status"] == "cancelled"
    assert issue["closed_at"]
    assert issue["claimed_by"] is None
    code, got = _run(root, "get", issue_id)
    body = got["issue"]["body"]  # type: ignore[index]
    assert isinstance(body, str)
    assert "## Cancelled" in body
    assert "no grouping need" in body


def test_tracker_issue_cancel_from_open_and_waiting(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    _, open_created = _run(root, "save", "--title", "Open card", "--status", "open")
    open_id = str(open_created["id"])
    assert _run(root, "cancel", open_id, "--by", "agent/a", "--reason", "drop")[0] == 0
    code, got = _run(root, "get", open_id)
    assert got["issue"]["status"] == "cancelled"  # type: ignore[index]

    _, wait_created = _run(root, "save", "--title", "Wait card", "--status", "open")
    wait_id = str(wait_created["id"])
    assert _run(root, "claim", wait_id, "--by", "agent/a")[0] == 0
    assert _run(root, "waiting", wait_id, "--by", "agent/a", "--reason", "ext")[0] == 0
    assert _run(root, "cancel", wait_id, "--by", "agent/a", "--reason", "abort")[0] == 0
    code, got2 = _run(root, "get", wait_id)
    assert got2["issue"]["status"] == "cancelled"  # type: ignore[index]


def test_tracker_issue_save_rejects_cancelled_status(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Y", "--status", "backlog")
    assert code == 0
    issue_id = str(created["id"])
    code, payload = _run(root, "save", "--id", issue_id, "--status", "cancelled")
    assert code != 0
    assert payload["code"] == "invalid_transition"
    code, create_bad = _run(root, "save", "--title", "Bad", "--status", "cancelled")
    assert code != 0
    assert create_bad["code"] == "invalid_transition"


def test_tracker_issue_claim_and_done_reject_cancelled(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    _, created = _run(root, "save", "--title", "Z", "--status", "backlog")
    issue_id = str(created["id"])
    assert _run(root, "cancel", issue_id, "--by", "agent/a", "--reason", "x")[0] == 0
    code, claim = _run(root, "claim", issue_id, "--by", "agent/b")
    assert code != 0
    assert claim["code"] == "invalid_transition"
    code, done = _run(root, "done", issue_id, "--by", "agent/b")
    assert code != 0
    assert done["code"] == "invalid_transition"


def test_tracker_issue_list_hides_cancelled_unless_include_done(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    _, live = _run(root, "save", "--title", "Live", "--status", "open")
    _, dead = _run(root, "save", "--title", "Dead", "--status", "backlog")
    dead_id = str(dead["id"])
    assert _run(root, "cancel", dead_id, "--by", "agent/a", "--reason", "x")[0] == 0
    code, listed = _run(root, "list")
    assert code == 0
    ids = {item["id"] for item in listed["issues"] if isinstance(item, dict)}  # type: ignore[union-attr]
    assert live["id"] in ids
    assert dead_id not in ids
    code, with_done = _run(root, "list", "--include-done")
    assert code == 0
    ids2 = {item["id"] for item in with_done["issues"] if isinstance(item, dict)}  # type: ignore[union-attr]
    assert dead_id in ids2
    code, now = _run(root, "list", "--now")
    assert code == 0
    ids_now = {item["id"] for item in now["issues"] if isinstance(item, dict)}  # type: ignore[union-attr]
    assert dead_id not in ids_now


def test_tracker_issue_save_rejects_legacy_open_pair(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Legacy names", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    for legacy in ("todo", "in_progress"):
        code, payload = _run(root, "save", "--id", issue_id, "--status", legacy)
        assert code != 0
        assert payload["ok"] is False
        assert payload["code"] == "invalid_args"
    code, create_bad = _run(root, "save", "--title", "Bad create", "--status", "todo")
    assert code != 0
    assert create_bad["code"] == "invalid_args"


def test_tracker_issue_normalize_legacy_open_pair(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    root.mkdir()
    (root / "ISSUES").mkdir()
    legacy = Issue(
        id="ISS-1",
        title="Old card",
        status="todo",
        body="body\n",
    )
    write_issue_atomic(root, legacy)
    # Force raw file to still say todo if write already normalized — rewrite raw.
    path = issue_path(root, "ISS-1")
    raw = path.read_text(encoding="utf-8").replace("status: open", "status: todo", 1)
    if "status: todo" not in raw:
        raw = path.read_text(encoding="utf-8").replace("status: in_progress", "status: todo", 1)
    path.write_text(raw, encoding="utf-8")

    issue = read_issue(root, "ISS-1")
    assert issue.status == "open"
    write_issue_atomic(root, issue)
    rewritten = path.read_text(encoding="utf-8")
    assert "status: open" in rewritten
    assert "status: todo" not in rewritten


def test_tracker_issue_claim_busy(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "save", "--title", "Busy", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert _run(root, "claim", issue_id, "--by", "agent/a")[0] == 0
    code, busy = _run(root, "claim", issue_id, "--by", "agent/b")
    assert code != 0
    assert busy["code"] == "busy"


def test_tracker_issue_list_now_and_waiting_release(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    _, a = _run(root, "save", "--title", "A", "--status", "open")
    _, b = _run(root, "save", "--title", "B", "--status", "backlog")
    code, listed = _run(root, "list", "--now")
    assert code == 0
    issues = listed["issues"]
    assert isinstance(issues, list)
    ids = {item["id"] for item in issues if isinstance(item, dict)}
    assert a["id"] in ids
    assert b["id"] not in ids

    issue_id = str(a["id"])
    assert _run(root, "claim", issue_id, "--by", "agent/a")[0] == 0
    assert _run(root, "waiting", issue_id, "--by", "agent/a", "--reason", "ext")[0] == 0
    code, got = _run(root, "get", issue_id)
    assert got["issue"]["status"] == "waiting"  # type: ignore[index]
    assert _run(root, "release", issue_id, "--by", "agent/a")[0] == 0
    code, got2 = _run(root, "get", issue_id)
    assert got2["issue"]["claimed_by"] is None  # type: ignore[index]


def test_tracker_issue_import_map_legacy_to_open() -> None:
    assert map_status("Todo") == "open"
    assert map_status("In Progress") == "open"
    assert map_status("started") == "open"
    assert map_status("backlog") == "backlog"


def test_tracker_issue_tracker_root_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    code, payload = tracker_cli.main(["--tracker-root", str(missing), "list"])
    assert code != 0
    assert payload["ok"] is False
    assert payload["code"] == "tracker_root_missing"


def test_tracker_issue_get_not_found(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    root.mkdir()
    code, payload = _run(root, "get", "ISS-999")
    assert code != 0
    assert payload["code"] == "not_found"


def test_tracker_issue_semantic_core_save_list(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    assert (
        _run(
            root,
            "hub",
            "registry",
            "add",
            "--canon-id",
            "park-parameters",
            "--title",
            "Park params",
        )[0]
        == 0
    )
    code, created = _run(root, "save", "--title", "Hubbed", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert created["issue"]["semantic_core"] is None  # type: ignore[index]

    code, saved = _run(root, "save", "--id", issue_id, "--semantic-core", "park-parameters")
    assert code == 0
    assert saved["issue"]["semantic_core"] == "park-parameters"  # type: ignore[index]

    code, listed = _run(root, "list", "--semantic-core", "park-parameters", "--include-done")
    assert code == 0
    ids = {item["id"] for item in listed["issues"] if isinstance(item, dict)}  # type: ignore[index]
    assert issue_id in ids

    code, unhubbed = _run(root, "list", "--unhubbed")
    assert code == 0
    un_ids = {item["id"] for item in unhubbed["issues"] if isinstance(item, dict)}  # type: ignore[index]
    assert issue_id not in un_ids

    code, got = _run(root, "get", issue_id)
    assert got["issue"]["semantic_core"] == "park-parameters"  # type: ignore[index]
    on_disk = issue_path(root, issue_id).read_text(encoding="utf-8")
    assert "semantic_core:" in on_disk and "park-parameters" in on_disk


def test_tracker_issue_semantic_core_clear_and_legacy_null(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    assert (
        _run(
            root,
            "hub",
            "registry",
            "add",
            "--canon-id",
            "park-parameters",
            "--title",
            "Park",
        )[0]
        == 0
    )
    code, created = _run(root, "save", "--title", "Clear me", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert _run(root, "save", "--id", issue_id, "--semantic-core", "park-parameters")[0] == 0
    code, cleared = _run(root, "save", "--id", issue_id, "--semantic-core", "")
    assert code == 0
    assert cleared["issue"]["semantic_core"] is None  # type: ignore[index]

    legacy = Issue(id="ISS-88", title="Legacy", status="open", body="x\n")
    write_issue_atomic(root, legacy)
    path = issue_path(root, "ISS-88")
    lines = path.read_text(encoding="utf-8").splitlines()
    raw = "\n".join(line for line in lines if not line.startswith("semantic_core:"))
    path.write_text(raw + ("\n" if not raw.endswith("\n") else ""), encoding="utf-8")
    issue = read_issue(root, "ISS-88")
    assert issue.semantic_core is None
    code, got = _run(root, "get", "ISS-88")
    assert got["issue"]["semantic_core"] is None  # type: ignore[index]


def test_tracker_issue_hub_registry_ensure_sync(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, reg = _run(
        root,
        "hub",
        "registry",
        "add",
        "--canon-id",
        "park-parameters",
        "--title",
        "Park params",
        "--om-ref",
        "info.model.semantic-core",
    )
    assert code == 0
    assert reg["ok"] is True

    code, ensured = _run(root, "hub", "ensure", "--canon-id", "park-parameters")
    assert code == 0
    hub_path = root / "HUBS" / "park-parameters.md"
    assert hub_path.is_file()

    code, created = _run(root, "save", "--title", "Member", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    assert _run(root, "save", "--id", issue_id, "--semantic-core", "park-parameters")[0] == 0

    code, synced = _run(root, "hub", "sync", "--canon-id", "park-parameters")
    assert code == 0
    body = hub_path.read_text(encoding="utf-8")
    assert f"[[ISSUES/{issue_id}]]" in body

    code, listed = _run(root, "hub", "list")
    assert code == 0
    hubs = listed["hubs"]
    assert isinstance(hubs, list)
    match = next(
        item for item in hubs if isinstance(item, dict) and item.get("id") == "park-parameters"
    )
    assert match["count"] == 1
    assert match["title"] == "Park params"


def test_tracker_issue_hub_canon_missing(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, payload = _run(root, "hub", "ensure", "--canon-id", "missing-core")
    assert code != 0
    assert payload["ok"] is False
    assert payload["code"] in {"canon_missing", "invalid_args"}

    code, created = _run(root, "save", "--title", "Orphan", "--status", "open")
    assert code == 0
    issue_id = str(created["id"])
    code, bad = _run(root, "save", "--id", issue_id, "--semantic-core", "missing-core")
    assert code != 0
    assert bad["ok"] is False
    assert bad["code"] in {"canon_missing", "invalid_args"}


def test_tracker_issue_domain_micromarket_allowlist(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(
        root,
        "save",
        "--title",
        "Fridge gap",
        "--status",
        "open",
        "--domain",
        "micromarket",
    )
    assert code == 0
    assert created["ok"] is True
    issue_id = str(created["id"])
    assert created["issue"]["domain"] == "micromarket"  # type: ignore[index]

    code, listed = _run(root, "list", "--domain", "micromarket")
    assert code == 0
    ids = [item["id"] for item in listed["issues"]]  # type: ignore[index]
    assert issue_id in ids

    code, patched = _run(root, "save", "--id", issue_id, "--domain", "snacks")
    assert code == 0
    assert patched["issue"]["domain"] == "snacks"  # type: ignore[index]
    code, back = _run(root, "save", "--id", issue_id, "--domain", "micromarket")
    assert code == 0
    assert back["issue"]["domain"] == "micromarket"  # type: ignore[index]

    code, cleared = _run(root, "save", "--id", issue_id, "--domain", "")
    assert code == 0
    assert cleared["issue"]["domain"] is None  # type: ignore[index]

    code, bad = _run(root, "save", "--title", "Typo", "--domain", "micromarkets")
    assert code != 0
    assert bad["ok"] is False
    assert bad["code"] == "invalid_args"


def test_tracker_project_save_get_list_attach(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(
        root,
        "project",
        "save",
        "--title",
        "Micromarket big-bang",
        "--link-discovery",
        "docs/discovery/demo",
        "--operating-case",
        "operating_cases.micromarket_loading_case",
    )
    assert code == 0
    assert created["ok"] is True
    assert created["created"] is True
    prj_id = str(created["id"])
    assert prj_id.startswith("PRJ-")
    assert created["project"]["status"] == "open"  # type: ignore[index]
    assert created["project"]["links"]["discovery"] == "docs/discovery/demo"  # type: ignore[index]
    assert created["project"]["operating_case"] == "operating_cases.micromarket_loading_case"  # type: ignore[index]

    code, got = _run(root, "project", "get", prj_id)
    assert code == 0
    assert got["project"]["id"] == prj_id  # type: ignore[index]
    body = got["project"]["body"]  # type: ignore[index]
    assert "Доска проекта.base#Open" in body
    assert "Доска проекта.base#Done" in body

    code, listed = _run(root, "project", "list")
    assert code == 0
    ids = [item["id"] for item in listed["projects"]]  # type: ignore[index]
    assert prj_id in ids

    code, issue = _run(root, "save", "--title", "Line A", "--status", "open")
    assert code == 0
    issue_id = str(issue["id"])
    code, attached = _run(root, "save", "--id", issue_id, "--project", prj_id)
    assert code == 0
    assert attached["issue"]["project"] == prj_id  # type: ignore[index]

    code, cleared = _run(root, "save", "--id", issue_id, "--project", "")
    assert code == 0
    assert cleared["issue"]["project"] is None  # type: ignore[index]


def test_tracker_project_attach_missing_errors(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, issue = _run(root, "save", "--title", "Orphan", "--status", "open")
    assert code == 0
    issue_id = str(issue["id"])
    code, bad = _run(root, "save", "--id", issue_id, "--project", "PRJ-999")
    assert code != 0
    assert bad["ok"] is False
    assert bad["code"] in {"not_found", "invalid_args"}


def test_tracker_project_invalid_status(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(root, "project", "save", "--title", "X")
    assert code == 0
    prj_id = str(created["id"])
    code, bad = _run(root, "project", "save", "--id", prj_id, "--status", "backlog")
    assert code != 0
    assert bad["ok"] is False


def test_tracker_issue_link_plan_and_discovery(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(
        root,
        "save",
        "--title",
        "Linked",
        "--status",
        "open",
        "--link-task",
        "tasks/demo/TASK.md",
        "--link-spec",
        "docs/specs/demo-design.md",
        "--link-plan",
        "docs/plans/demo/",
        "--link-discovery",
        "docs/discovery/demo/",
    )
    assert code == 0
    issue = created["issue"]
    assert isinstance(issue, dict)
    links = issue["links"]
    assert isinstance(links, dict)
    assert links["task"] == "tasks/demo/TASK.md"
    assert links["spec"] == "docs/specs/demo-design.md"
    assert links["plan"] == "docs/plans/demo/"
    assert links["discovery"] == "docs/discovery/demo/"

    issue_id = str(created["id"])
    code, patched = _run(
        root,
        "save",
        "--id",
        issue_id,
        "--link-plan",
        "docs/plans/demo-v2/",
    )
    assert code == 0
    links2 = patched["issue"]["links"]  # type: ignore[index]
    assert isinstance(links2, dict)
    assert links2["plan"] == "docs/plans/demo-v2/"
    assert links2["task"] == "tasks/demo/TASK.md"
    assert links2["spec"] == "docs/specs/demo-design.md"
    assert links2["discovery"] == "docs/discovery/demo/"


def test_tracker_issue_gate_require(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    code, created = _run(
        root,
        "save",
        "--title",
        "Gate me",
        "--status",
        "open",
        "--link-task",
        "tasks/demo/TASK.md",
        "--link-spec",
        "docs/specs/demo-design.md",
    )
    assert code == 0
    issue_id = str(created["id"])

    code, missing = _run(root, "gate", issue_id, "--require", "task,spec,plan")
    assert code != 0
    assert missing["ok"] is False
    assert missing["code"] == "gate_failed"
    assert "plan" in missing["missing"]  # type: ignore[operator]

    assert _run(root, "save", "--id", issue_id, "--link-plan", "docs/plans/demo/")[0] == 0
    code, ok = _run(root, "gate", issue_id, "--require", "task,spec,plan")
    assert code == 0
    assert ok["ok"] is True
    assert ok["missing"] == []

    code, absent = _run(root, "gate", "ISS-999", "--require", "task")
    assert code != 0
    assert absent["ok"] is False
    assert absent["code"] == "not_found"
