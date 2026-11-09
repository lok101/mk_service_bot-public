from __future__ import annotations

from pathlib import Path


def test_machine_list_deps_gets_domain_product_store() -> None:
    text = Path("src/infrastructure/composition/runtime.py").read_text(encoding="utf-8")
    start = text.index("return MachineListDeps(")
    builder_body = text[start:]
    assert "domain_product_store=" in builder_body
    assert "build_domain_product_store" in text
