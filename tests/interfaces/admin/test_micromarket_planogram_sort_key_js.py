from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SCRIPT = Path("src/interfaces/admin/static/micromarket_planogram_sort_key.js").resolve()


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
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_planogram_sort_key_normalizes_yo_and_casefolds() -> None:
    # happy: lower + ё→е; sortKey без pending; compare — группы false→true
    line = {"name": "\u0401\u043b\u043a\u0430", "domainProductId": "p1", "productCode": ""}
    key = _call("m.sortKey(" + json.dumps(line) + ")")
    assert key == ["\u0435\u043b\u043a\u0430", "p1", ""]
    with_pending = _call("m.sortKey(" + json.dumps({**line, "pendingExit": True}) + ")")
    assert with_pending == key
    ordered = _call(
        "(["
        + json.dumps({"name": "Апельсин", "domainProductId": "a", "pendingExit": True})
        + ","
        + json.dumps({"name": "Банан", "domainProductId": "b", "pendingExit": False})
        + ","
        + json.dumps({"name": "Яблоко", "domainProductId": "c", "pendingExit": True})
        + "].sort(m.comparePlanogramLines).map(l => l.domainProductId))"
    )
    assert ordered == ["b", "a", "c"]


def test_planogram_sort_key_tie_breaks_by_domain_id_then_code() -> None:
    # edge: одинаковые имена — domain_product_id, затем product_code; без localeCompare
    lines = [
        {"name": "\u0421\u043e\u043a", "domainProductId": "b", "productCode": ""},
        {"name": "\u0421\u043e\u043a", "domainProductId": "a", "productCode": ""},
        {"name": "\u0412\u043e\u0434\u0430", "domainProductId": "", "productCode": "2312"},
        {"name": "\u0412\u043e\u0434\u0430", "domainProductId": "", "productCode": "2311"},
    ]
    ordered = _call(json.dumps(lines) + ".sort(m.comparePlanogramLines).map(m.sortKey)")
    assert ordered == [
        ["\u0432\u043e\u0434\u0430", "", "2311"],
        ["\u0432\u043e\u0434\u0430", "", "2312"],
        ["\u0441\u043e\u043a", "a", ""],
        ["\u0441\u043e\u043a", "b", ""],
    ]
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "localeCompare" not in source
