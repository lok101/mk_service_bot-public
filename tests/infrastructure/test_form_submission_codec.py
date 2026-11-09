from __future__ import annotations

from decimal import Decimal

from src.domain.form_submission import FrozenInventoryLine, FrozenProductSpec
from src.domain.product_catalog import ProductUnit
from src.infrastructure.mongodb.form_submission_codec import (
    deserialize_decimal,
    deserialize_product_unit,
    document_to_frozen_line,
    frozen_line_to_document,
    serialize_decimal,
    serialize_product_unit,
)


def test_decimal_serialization_round_trip() -> None:
    assert deserialize_decimal(serialize_decimal(Decimal("12.5"))) == Decimal("12.5")
    assert serialize_decimal(None) is None
    assert deserialize_decimal(None) is None


def test_product_unit_serialization_round_trip() -> None:
    assert deserialize_product_unit(serialize_product_unit(ProductUnit.GRAM)) == ProductUnit.GRAM


def test_frozen_line_document_round_trip() -> None:
    line = FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee-1",
            name="Кофе",
            unit=ProductUnit.GRAM,
            pack_size=Decimal("20"),
            moysklad_quantity_factor=Decimal("0.001"),
        ),
        quantity=Decimal("3"),
    )
    document = frozen_line_to_document(line)
    restored = document_to_frozen_line(document)
    assert restored.form_title == "Кофе"
    assert restored.quantity == Decimal("3")
    assert restored.product_spec.product_code == "coffee-1"
