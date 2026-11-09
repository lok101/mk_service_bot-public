from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent

_MACHINE = "701"
_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DAY = date(2026, 11, 3)


def _pending(
    *,
    quantities: tuple[tuple[str, Decimal], ...] | None = None,
    inventory_id: str = "inv-1",
) -> PendingMicromarketInvent:
    return PendingMicromarketInvent(
        machine_code=_MACHINE,
        inventory_id=inventory_id,
        quantities=quantities or (("d-1", Decimal("2")), ("d-2", Decimal("0"))),
        submitted_at=_NOW,
        operational_day=_DAY,
        performed_technician_id="t1",
        performed_technician_name="Tech",
    )


def test_pending_holds_snapshot() -> None:
    pending = _pending()
    assert pending.machine_code == _MACHINE
    assert pending.quantity_map()["d-1"] == Decimal("2")
    assert pending.quantity_map()["d-2"] == Decimal("0")


def test_pending_rejects_empty_machine_code() -> None:
    with pytest.raises(ValueError, match="machine_code"):
        PendingMicromarketInvent(
            machine_code=" ",
            inventory_id="inv-1",
            quantities=(("d-1", Decimal("1")),),
            submitted_at=_NOW,
            operational_day=_DAY,
        )


def test_pending_rejects_duplicate_codes() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _pending(quantities=(("d-1", Decimal("1")), ("d-1", Decimal("2"))))
