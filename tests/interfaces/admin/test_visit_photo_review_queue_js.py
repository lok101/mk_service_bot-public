"""JS contract: visit photo queue dual-export parse + URL helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SCRIPT = Path("src/interfaces/admin/static/visit_photo_review_queue.js").resolve()


def _call(expr: str) -> object:
    completed = subprocess.run(
        [
            "node",
            "-e",
            "const m=require(" + json.dumps(str(_SCRIPT)) + ");"
            "process.stdout.write(JSON.stringify(" + expr + "));",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def test_visit_photo_queue_parse_valid_groups() -> None:
    # happy: valid JSON array → groups
    groups = _call('m.parseCarouselGroups(\'[{"group_id":"g1","frames":[]}]\')')
    assert groups == [{"group_id": "g1", "frames": []}]


def test_visit_photo_queue_parse_invalid_json_returns_empty() -> None:
    # edge: битый JSON → []
    assert _call("m.parseCarouselGroups('{not-json')") == []
    assert _call("m.parseCarouselGroups('null')") == []
    assert _call("m.parseCarouselGroups('{}')") == []


def test_visit_photo_queue_view_and_dispose_url_helpers() -> None:
    # happy: view URL shape; dispose includes batch id
    assert (
        _call('m.viewFrameUrl("batch-1", 3)') == "/admin/visit-photo-review/frames/batch-1/3/view"
    )
    dispose = _call('m.disposeActionUrl("batch-9", "tab=problems")')
    assert dispose.startswith("/admin/visit-photo-review/blocks/batch-9/unrecognized/dispose?")
    assert "tab=problems" in dispose
