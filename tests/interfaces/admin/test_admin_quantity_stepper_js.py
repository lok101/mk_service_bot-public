from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SCRIPT = Path("src/interfaces/admin/static/admin_quantity_stepper.js").resolve()
_CSS = Path("src/interfaces/admin/static/admin.css")
_PARTIAL = Path("src/interfaces/admin/templates/_admin_quantity_stepper.html")


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


def test_qty_stepper_nudge_and_disabled_at_bounds() -> None:
    # happy: ±1; на min/max соответствующая кнопка disabled
    assert _call("m.nudge(12, 1, 0, 50)") == 13
    assert _call("m.nudge(12, -1, 0, 50)") == 11
    assert _call("m.nudge(0, -1, 0, 50)") == 0
    assert _call("m.nudge(50, 1, 0, 50)") == 50
    assert _call("m.disabledState(0, 0, 50)") == {"minus": True, "plus": False}
    assert _call("m.disabledState(50, 0, 50)") == {"minus": False, "plus": True}
    assert _call("m.disabledState(12, 0, 50)") == {"minus": False, "plus": False}


def test_qty_stepper_blur_clamps_empty_and_non_number_to_min() -> None:
    # edge: blur clamp 0…50; пустое/нечисло → min
    assert _call('m.normalizeInput("-3", 0, 50, false)') == 0
    assert _call('m.normalizeInput("99", 0, 50, false)') == 50
    assert _call('m.normalizeInput("", 0, 50, false)') == 0
    assert _call('m.normalizeInput("abc", 0, 50, false)') == 0
    assert _call('m.normalizeInput("12.7", 0, 50, true)') == 13
    assert _call('m.normalizeInput("12.2", 0, 50, true)') == 12


def test_qty_stepper_loading_fraction_becomes_integer_on_blur() -> None:
    # edge: loading need/launch — дробь → целое в UI на blur (integer mode)
    assert _call('m.normalizeInput("3.6", 0, 50, true)') == 4
    assert _call('m.normalizeInput("3,4", 0, 50, true)') == 3
    assert _call('m.normalizeInput("0.5", 0, 50, true)') == 1
    assert _call('m.normalizeInput("50.9", 0, 50, true)') == 50


def test_qty_stepper_css_and_partial_use_prod_class_names() -> None:
    # happy: прод-классы без demo-; Jinja partial с параметрами
    css = _CSS.read_text(encoding="utf-8")
    assert ".admin-qty-stepper" in css
    assert ".admin-qty-btn" in css
    assert ".admin-qty-input" in css
    assert "demo-qty-" not in css
    partial = _PARTIAL.read_text(encoding="utf-8")
    assert "admin-qty-stepper" in partial
    assert "admin-qty-btn" in partial
    assert "admin-qty-input" in partial
    assert "{{ name }}" in partial or "name=" in partial
    assert "data-min" in partial
    assert "data-max" in partial


def test_qty_stepper_buttons_are_out_of_tab_order() -> None:
    # happy: Tab идёт по полям SKU, не по −/+
    partial = _PARTIAL.read_text(encoding="utf-8")
    assert partial.count('class="admin-qty-btn"') == 4
    assert partial.count('tabindex="-1"') == 4
