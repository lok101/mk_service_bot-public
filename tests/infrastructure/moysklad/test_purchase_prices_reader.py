from __future__ import annotations

from src.application.matrix_automation import PurchasePricesBatchError
from src.infrastructure.moysklad.purchase_prices.models import (
    PurchaseAttributes,
    PurchaseAttributesBatchResult,
)
from src.infrastructure.moysklad.purchase_prices.reader import MoySkladPurchaseAttributesReader


class _Client:
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        attributes = {
            code: PurchaseAttributes(buy_price="10.00", volume=12) for code in product_codes
        }
        return PurchaseAttributesBatchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


class _PartialClient:
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        first = next(iter(product_codes))
        attributes = {first: PurchaseAttributes(buy_price="10.00", volume=12)}
        return PurchaseAttributesBatchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


class _FailingClient:
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        raise RuntimeError("ms down")


def test_fetch_purchase_attributes_happy_path() -> None:
    reader = MoySkladPurchaseAttributesReader(client=_Client())
    result = reader.fetch_purchase_attributes(frozenset({"A", "B"}))
    assert result.attributes["A"].buy_price == "10.00"
    assert result.attributes["B"].volume == 12
    assert result.cards_found == 2


def test_fetch_attributes_returns_fetch_result() -> None:
    reader = MoySkladPurchaseAttributesReader(client=_Client())
    result = reader.fetch_attributes(frozenset({"A"}))
    assert result.attributes["A"] == ("10.00", 12)
    assert result.cards_found == 1
    assert result.supply_http_failed == frozenset()


def test_fetch_attributes_tuple_has_no_supplier_fields() -> None:
    reader = MoySkladPurchaseAttributesReader(client=_Client())
    result = reader.fetch_attributes(frozenset({"A"}))
    price, volume = result.attributes["A"]
    assert price == "10.00"
    assert volume == 12
    assert not hasattr(result.attributes["A"], "supplier_id")
    assert len(result.attributes["A"]) == 2


def test_fetch_purchase_attributes_partial_response() -> None:
    reader = MoySkladPurchaseAttributesReader(client=_PartialClient())
    result = reader.fetch_purchase_attributes(frozenset({"A", "B"}))
    assert len(result.attributes) == 1
    assert next(iter(result.attributes)) in {"A", "B"}
    assert result.cards_found == 1


def test_fetch_purchase_attributes_total_fail_raises_batch_error() -> None:
    reader = MoySkladPurchaseAttributesReader(client=_FailingClient())
    try:
        reader.fetch_purchase_attributes(frozenset({"A"}))
    except PurchasePricesBatchError as exc:
        assert "ms down" in str(exc)
    else:
        raise AssertionError("expected PurchasePricesBatchError")


def test_fetch_purchase_attributes_rejects_plain_dict_client() -> None:
    class _DictClient:
        def fetch_purchase_attributes(
            self,
            product_codes: frozenset[str],
        ) -> dict[str, PurchaseAttributes]:
            return {code: PurchaseAttributes(buy_price="1", volume=1) for code in product_codes}

    reader = MoySkladPurchaseAttributesReader(client=_DictClient())
    try:
        reader.fetch_purchase_attributes(frozenset({"A"}))
    except PurchasePricesBatchError:
        return
    raise AssertionError("expected PurchasePricesBatchError for plain dict")
