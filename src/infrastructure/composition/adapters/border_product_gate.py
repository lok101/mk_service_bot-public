from __future__ import annotations

from beartype import beartype

from src.application.product_identity.border_registration import (
    BorderRegistrationStore,
    border_status,
    note_unregistered_codes,
    unregistered_codes_among,
)
from src.application.product_identity.ports import DomainProductStore


@beartype
class ProductIdentityBorderGate:
    def __init__(
        self,
        *,
        products: DomainProductStore,
        border: BorderRegistrationStore,
    ) -> None:
        self._products = products
        self._border = border

    @beartype
    def unregistered_among(self, codes: tuple[str, ...]) -> tuple[str, ...]:
        return unregistered_codes_among(
            codes,
            products=self._products,
            border=self._border,
        )

    @beartype
    def is_ignored(self, code: str) -> bool:
        return (
            border_status(
                code,
                products=self._products,
                border=self._border,
            )
            == "ignored"
        )

    @beartype
    def note_unregistered(self, codes: tuple[str, ...]) -> None:
        note_unregistered_codes(
            codes,
            products=self._products,
            border=self._border,
        )
