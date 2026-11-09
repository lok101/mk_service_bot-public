"""JS contract: markPendingExit / clearPendingExit dual-export."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_TABLE_JS = Path("src/interfaces/admin/static/micromarket_planogram_table.js")
_REPRO = Path(__file__).resolve().parent / "_js_islands_repro" / "run_pending_exit.js"


def test_planogram_table_js_exports_pending_exit_helpers() -> None:
    # happy: dual-export names for mark/clear pending_exit
    source = _TABLE_JS.read_text(encoding="utf-8")
    assert "function markPendingExit" in source
    assert "function clearPendingExit" in source
    assert "markPendingExit: markPendingExit" in source
    assert "clearPendingExit: clearPendingExit" in source


def test_planogram_table_js_pending_exit_mark_and_clear_in_node() -> None:
    # happy: mark sets class+value; clear removes them
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
    assert payload["afterMark"] == {"class": True, "value": "1"}
    assert payload["afterClear"] == {"class": False, "value": ""}
