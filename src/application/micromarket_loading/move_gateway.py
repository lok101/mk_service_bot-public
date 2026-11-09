from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


class MoveAlreadyGone(Exception):
    """Move document is already absent in MoySklad."""


class MoveDeleteFailed(Exception):
    """Move document delete failed for a reason other than missing."""


@runtime_checkable
class MicromarketMoveGateway(Protocol):
    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str: ...

    def delete_move(self, *, move_id: str) -> None: ...

    def move_moment(self, *, move_id: str) -> datetime | None: ...

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool: ...

    def warehouse_qty(self, product_code: str) -> Decimal: ...

    def warehouse_qty_by_codes(
        self,
        product_codes: Sequence[str],
    ) -> Mapping[str, Decimal]: ...
