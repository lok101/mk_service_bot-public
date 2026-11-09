from __future__ import annotations

from src.application.matrix_automation import (
    PurchaseAttributesFetchResult,
    PurchasePricesBatchError,
)


def test_purchase_symbols_importable_from_matrix_automation_barrel() -> None:
    assert issubclass(PurchasePricesBatchError, Exception)
    result = PurchaseAttributesFetchResult(attributes={}, cards_found=0)
    assert result.cards_found == 0
    assert result.supply_http_failed == frozenset()
