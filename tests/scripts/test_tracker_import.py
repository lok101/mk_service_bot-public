from __future__ import annotations

import json
from pathlib import Path

from scripts.tracker_issue_lib import cli as tracker_cli
from scripts.tracker_issue_lib.store import list_issues


def _run(root: Path, *argv: str) -> tuple[int, dict[str, object]]:
    code, payload = tracker_cli.main(["--tracker-root", str(root), *argv])
    assert isinstance(payload, dict)
    return code, payload


def test_tracker_import_idempotent_legacy_id(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    fixture = Path(__file__).resolve().parent / "fixtures" / "tracker_import_sample.json"
    code, first = _run(root, "import-json", "--file", str(fixture))
    assert code == 0
    assert first["created"] == 2
    assert first["errors"] == 0
    files_after_first = {issue.legacy_id for issue in list_issues(root)}
    assert files_after_first == {"LOK-1", "LOK-2"}

    code, second = _run(root, "import-json", "--file", str(fixture))
    assert code == 0
    assert second["created"] == 0
    assert int(second["updated"]) + int(second["skipped"]) == 2
    assert len(list_issues(root)) == 2


def test_tracker_import_malformed_counts_error(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps([{"title": "no id"}, {"id": "LOK-9", "title": "ok"}]), encoding="utf-8"
    )
    code, payload = _run(root, "import-json", "--file", str(bad))
    assert code == 0
    assert payload["created"] == 1
    assert payload["errors"] == 1
    assert len(list_issues(root)) == 1
