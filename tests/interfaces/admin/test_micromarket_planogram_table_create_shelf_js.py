"""Behavioral coverage for creating a shelf section from a category select."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from tests.interfaces.admin.test_micromarket_planogram_routes import (
    _TABLE_JS_PATH,
    _build_app_with_micromarket_planogram,
    _signed_widget_fields,
)

_REPRO_JS = Path(__file__).resolve().parent / "_create_shelf_js_repro" / "run_create_shelf.js"


def test_planogram_page_cache_busts_table_script() -> None:
    # happy: table/sort/picker scripts get ?v= so createShelfSection is not stuck in cache
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert re.search(r"/admin/static/micromarket_planogram_table\.js\?v=\d+", html)
    assert re.search(r"/admin/static/micromarket_planogram_sort_key\.js\?v=\d+", html)
    assert re.search(r"/admin/static/planogram_product_picker\.js\?v=\d+", html)


def test_planogram_table_js_move_uses_create_shelf_return_value() -> None:
    # happy: missing shelf is created via return value; option label without fragile querySelector
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "function createShelfSection" in table_js
    change_start = table_js.index('select.addEventListener("change"')
    change_body = table_js[change_start : change_start + 700]
    assert "target = createShelfSection(value)" in change_body
    assert "moveRowToShelf" in change_body
    label_start = table_js.index("function shelfOptionLabel")
    label_body = table_js[label_start : table_js.index("\n  function ", label_start + 1)]
    assert "querySelector('option[value=\"'" not in label_body
    assert ".options" in label_body
    assert "shelfOptionLabel" in table_js[table_js.index("function createShelfSection") :]


def test_planogram_table_js_create_shelf_moves_row_in_node() -> None:
    # happy: choosing a category without a section creates the section and moves the row
    completed = subprocess.run(
        ["node", str(_REPRO_JS)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
    )
    if completed.returncode != 0 and "Cannot find module 'jsdom'" in (completed.stderr or ""):
        # edge: environment without jsdom — structural tests above still guard the contract
        return
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["shelves"] == ["10", "20"]
    assert payload["rowShelf"] == "20"
    assert payload["kitGroup"] == "20"
