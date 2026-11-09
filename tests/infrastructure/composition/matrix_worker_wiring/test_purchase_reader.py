from __future__ import annotations

from pathlib import Path

from .fakes import _enabled_settings


def test_build_purchase_attributes_reader_uses_empty_client_without_remap(
    tmp_path: Path,
) -> None:
    # happy: matrix-worker never builds Remap HTTP (ADR-0083)
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.moysklad.purchase_prices.reader import (
        MoySkladPurchaseAttributesReader,
    )

    reader, _close = wire_mod.build_purchase_attributes_reader(_enabled_settings(tmp_path))
    assert isinstance(reader, MoySkladPurchaseAttributesReader)
    assert isinstance(reader._client, wire_mod._EmptyPurchaseClient)
