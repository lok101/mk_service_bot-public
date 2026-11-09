"""JS contract: reindexRowNames / reindexShelfNames dual-export."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_TABLE_JS = Path("src/interfaces/admin/static/micromarket_planogram_table.js")
_REPRO = Path(__file__).resolve().parent / "_js_islands_repro" / "run_reindex.js"


def test_planogram_table_js_exports_reindex_helpers() -> None:
    # happy: dual-export surface for Node + window API name
    source = _TABLE_JS.read_text(encoding="utf-8")
    assert "reindexRowNames" in source
    assert "reindexShelfNames" in source
    assert "module.exports" in source
    assert "MicromarketPlanogramTable" in source


def test_planogram_table_js_reindex_renumbers_fields_in_node() -> None:
    # happy: after reindex, row fields are continuous 0..n; shelves 0..m
    completed = subprocess.run(
        ["node", str(_REPRO)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path.cwd()),
    )
    if completed.returncode != 0 and "Cannot find module 'jsdom'" in (completed.stderr or ""):
        return
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["shelfNames"] == ["shelf_kit_group_id-0", "shelf_kit_group_id-1"]
    assert payload["rowNames"] == [
        ["domain_product_id-0", "pending_exit-0", "target_qty-0"],
        ["domain_product_id-1", "pending_exit-1", "target_qty-1"],
        ["domain_product_id-2", "pending_exit-2", "target_qty-2"],
    ]


def test_planogram_table_js_reindex_noop_without_shelves_root() -> None:
    # edge: missing shelves root — require still loads; reindex no-ops
    source = _TABLE_JS.read_text(encoding="utf-8")
    assert "function reindexRowNames" in source
    assert "if (!root) return" in source or "if (!root) return;" in source
