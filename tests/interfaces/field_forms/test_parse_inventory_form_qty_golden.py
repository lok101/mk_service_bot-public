from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from src.interfaces.google_forms.webhook.inventory_qty_parse import parse_inventory_form_qty

_FIXTURE = Path(__file__).parent / "fixtures" / "inventory_qty_parse_golden.json"
_JS = Path("src/interfaces/field_forms/static/inventory_qty_parse.js")


def _cases() -> list[dict[str, object]]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda c: repr(c["raw"]))
def test_parse_inventory_form_qty_golden_python(case: dict[str, object]) -> None:
    """happy/error: Python parse matches golden fixture."""
    raw = str(case["raw"])
    if case["ok"]:
        assert parse_inventory_form_qty(raw) == Decimal(str(case["value"]))
    else:
        with pytest.raises(ValueError):
            parse_inventory_form_qty(raw)


def test_parse_inventory_form_qty_golden_js_contract() -> None:
    """happy: Node port of parse matches golden (same fixture as Python)."""
    if not _JS.is_file():
        pytest.fail(f"missing {_JS}")
    script = f"""
const {{ parseInventoryFormQty }} = require('./{_JS.as_posix()}');
const cases = {json.dumps(_cases(), ensure_ascii=False)};
const out = [];
for (const c of cases) {{
  try {{
    const v = parseInventoryFormQty(c.raw);
    out.push({{ raw: c.raw, ok: true, value: v }});
  }} catch (e) {{
    out.push({{ raw: c.raw, ok: false }});
  }}
}}
process.stdout.write(JSON.stringify(out));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path.cwd()),
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    js_out = json.loads(completed.stdout)
    for expected, actual in zip(_cases(), js_out, strict=True):
        assert actual["ok"] is expected["ok"]
        if expected["ok"]:
            assert Decimal(str(actual["value"])) == Decimal(str(expected["value"]))
