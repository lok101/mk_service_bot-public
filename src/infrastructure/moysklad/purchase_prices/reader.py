from __future__ import annotations

from beartype import beartype

from src.application.matrix_automation import (
    PurchaseAttributesFetchResult,
    PurchasePricesBatchError,
)
from src.infrastructure.moysklad.purchase_prices.models import PurchaseAttributesBatchResult


@beartype
class MoySkladPurchaseAttributesReader:
    def __init__(self, *, client: object) -> None:
        self._client = client

    @beartype
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        if not product_codes:
            return PurchaseAttributesBatchResult(attributes={}, cards_found=0)
        fetch = getattr(self._client, "fetch_purchase_attributes", None)
        if fetch is None:
            msg = "client missing fetch_purchase_attributes"
            raise PurchasePricesBatchError(msg)
        try:
            result = fetch(product_codes)
        except Exception as exc:  # noqa: BLE001
            raise PurchasePricesBatchError(str(exc)) from exc
        if not isinstance(result, PurchaseAttributesBatchResult):
            msg = "client must return PurchaseAttributesBatchResult"
            raise PurchasePricesBatchError(msg)
        return result

    @beartype
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        batch = self.fetch_purchase_attributes(product_codes)
        return PurchaseAttributesFetchResult(
            attributes={
                code: (value.buy_price, value.volume) for code, value in batch.attributes.items()
            },
            cards_found=batch.cards_found,
            supply_http_failed=batch.supply_http_failed,
        )
