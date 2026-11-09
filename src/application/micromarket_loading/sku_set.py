from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from beartype import beartype

from src.application.product_identity.number import canonical_domain_number


@beartype
def micromarket_inventory_sku_codes(
    *,
    active_planogram_codes: Sequence[str],
    stock_qty: Mapping[str, Decimal],
    pending_exit_planogram_codes: Sequence[str] = (),
) -> frozenset[str]:
    """Membership set for micromarket inventory Form SKUs (order comes from pages)."""
    codes = {code for code in active_planogram_codes if code}
    codes |= {code for code in pending_exit_planogram_codes if code}
    codes |= {
        code
        for code, qty in stock_qty.items()
        if qty > 0 and canonical_domain_number(code) is not None
    }
    return frozenset(codes)
