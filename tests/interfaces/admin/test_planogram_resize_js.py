from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SCRIPT = Path("src/interfaces/admin/static/planogram_resize.js").resolve()


def _apply(
    cells: list[dict[str, object]],
    old_shelves: int,
    old_slots: int,
    new_shelves: int,
    new_slots: int,
    confirmed: bool,
) -> dict[str, object]:
    expr = (
        "m.applyResize("
        + json.dumps(cells)
        + f", {old_shelves}, {old_slots}, {new_shelves}, {new_slots}, "
        + json.dumps(confirmed)
        + ")"
    )
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
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def test_planogram_grow_preserves_existing_cells() -> None:
    # happy
    payload = _apply(
        [{"shelf": 0, "slot": 0, "product": "A", "line": "1", "merge": False}],
        1,
        1,
        2,
        2,
        True,
    )
    assert payload["needsConfirm"] is False
    cells = payload["cells"]
    assert isinstance(cells, list)
    assert any(
        item.get("product") == "A" and item.get("shelf") == 0 and item.get("slot") == 0
        for item in cells
        if isinstance(item, dict)
    )


def test_planogram_shrink_with_data_requires_confirm() -> None:
    # edge
    payload = _apply(
        [
            {"shelf": 0, "slot": 0, "product": "", "line": "", "merge": False},
            {"shelf": 0, "slot": 1, "product": "B", "line": "2", "merge": False},
        ],
        1,
        2,
        1,
        1,
        False,
    )
    assert payload["needsConfirm"] is True
    assert payload["slots"] == 2


def test_planogram_shrink_cancel_keeps_dimensions() -> None:
    # edge
    payload = _apply(
        [{"shelf": 0, "slot": 1, "product": "B", "line": "2", "merge": False}],
        1,
        2,
        1,
        1,
        False,
    )
    assert payload["shelves"] == 1
    assert payload["slots"] == 2


def test_planogram_shrink_merge_on_slice_counts_as_data() -> None:
    # edge: merge span 2, anchor slot 0, shrink 2→1 slots
    payload = _apply(
        [{"shelf": 0, "slot": 0, "product": "A", "line": "1", "merge": True}],
        1,
        2,
        1,
        1,
        False,
    )
    assert payload["needsConfirm"] is True
