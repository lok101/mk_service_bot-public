from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.quantities import packages_to_base_quantity


def test_packages_to_base_quantity_multiplies() -> None:
    assert packages_to_base_quantity(
        packages=Decimal("4"),
        pack_size=Decimal("1000"),
    ) == Decimal("4000")


def test_packages_to_base_quantity_rejects_non_positive_pack_size() -> None:
    with pytest.raises(ValueError, match="pack_size"):
        packages_to_base_quantity(packages=Decimal("1"), pack_size=Decimal("0"))
