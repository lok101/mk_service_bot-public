from __future__ import annotations

from pathlib import Path


def test_wire_passes_resolver_only_when_flag_on() -> None:
    wire = Path(
        "src/infrastructure/composition/wiring/wire_settlement.py",
    ).read_text(encoding="utf-8")
    assert "build_domain_product_resolver" in wire
    assert "domain_product_identity_enabled=settings.domain_product_identity.enabled" in wire
    assemble = Path(
        "src/infrastructure/composition/wiring/assemble.py",
    ).read_text(encoding="utf-8")
    start = assemble.index("settlement_wiring = wire_settlement(")
    chunk = assemble[start : start + 1200]
    assert "reference_provider=reference_provider" in chunk


def test_wire_drain_uses_kit_shop_resolver() -> None:
    wire = Path(
        "src/infrastructure/composition/wiring/wire_settlement.py",
    ).read_text(encoding="utf-8")
    assert "build_domain_product_kit_shop_resolver" in wire
    drain_chunk = wire[wire.index("drain = DrainKitShopSalesBacklog(") :]
    drain_chunk = drain_chunk[: drain_chunk.index(")\n")]
    assert "build_domain_product_kit_shop_resolver" in drain_chunk
    assert "resolve_sale_code=" in drain_chunk
