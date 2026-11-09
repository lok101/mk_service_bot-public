from __future__ import annotations

from pathlib import Path


def test_vending_builders_pass_domain_product_flag() -> None:
    needle = "domain_product_identity_enabled=settings.domain_product_identity.enabled"
    wire = Path(
        "src/infrastructure/composition/wiring/wire_settlement.py",
    ).read_text(encoding="utf-8")
    auto = Path(
        "src/infrastructure/composition/factories/auto_reconcile.py",
    ).read_text(encoding="utf-8")
    assert wire.count(needle) == 2
    assert auto.count(needle) == 1
    assert "build_domain_product_resolver" in wire
    assert "build_domain_product_resolver" in auto


def test_vending_builders_keep_resolve_sale_code_builder() -> None:
    wire = Path(
        "src/infrastructure/composition/wiring/wire_settlement.py",
    ).read_text(encoding="utf-8")
    kit_chunk_start = wire.index("kitvending_client = build_kitvending_client(")
    kit_chunk = wire[kit_chunk_start : kit_chunk_start + 800]
    assert "build_domain_product_resolver" in kit_chunk
    assert "build_domain_product_kit_shop_resolver" not in kit_chunk
