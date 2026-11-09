from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.domain.calendar import operational_day
from src.domain.micromarket_loading.order import (
    DraftLine,
    MicromarketLoadingCycle,
    OrderStatus,
)
from src.domain.micromarket_loading.order_errors import SecondCommandRejected
from src.domain.micromarket_loading.order_events import OPS_CONFIRMED_WITHOUT_RECOUNT

_TZ = ZoneInfo("Europe/Moscow")
_HOUR = 6
_AT = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)


def _line() -> DraftLine:
    return DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )


def _open(cycle: MicromarketLoadingCycle, *, at: datetime, order_id: str) -> None:
    cycle.open_order(
        order_id=order_id,
        move_id=f"move-{order_id}",
        lines=(_line(),),
        opened_at=at,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )


def test_rehydrate_matches_command_path() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft((_line(),))
    _open(cycle, at=_AT, order_id="order-1")
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.status is OrderStatus.OPEN
    assert restored.order_id == "order-1"
    assert restored.move_id == "move-order-1"
    assert restored.lines[0].launch_qty == Decimal("2")
    assert restored.opened_operational_day == operational_day(_AT, _TZ, _HOUR)


def test_second_open_rejected_while_open() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    with pytest.raises(SecondCommandRejected):
        _open(cycle, at=_AT, order_id="order-2")
    assert cycle.status is OrderStatus.OPEN
    assert cycle.order_id == "order-1"


_SHELF_BEFORE: tuple[tuple[str, Decimal], ...] = (("2311", Decimal("1")),)


def test_second_open_rejected_while_recounted() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=_SHELF_BEFORE,
    )
    with pytest.raises(SecondCommandRejected):
        _open(cycle, at=_AT, order_id="order-2")
    assert cycle.status is OrderStatus.RECOUNTED
    assert cycle.order_id == "order-1"


def test_record_launch_intent_rejected_while_recounted() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=_SHELF_BEFORE,
    )
    with pytest.raises(SecondCommandRejected):
        cycle.record_launch_intent(order_id="order-2")
    assert cycle.order_id == "order-1"
    assert cycle.status is OrderStatus.RECOUNTED


def test_open_allowed_after_rollback_same_operational_day() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.roll_back(at=_AT)
    _open(cycle, at=_AT, order_id="order-2")
    assert cycle.status is OrderStatus.OPEN
    assert cycle.order_id == "order-2"


def test_rollback_clears_visit_id() -> None:
    """happy: OrderRolledBack unlinks visit_id on the cycle."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.link_visit("scheduled:701:2026-09-24")
    assert cycle.visit_id == "scheduled:701:2026-09-24"
    cycle.roll_back(at=_AT)
    assert cycle.status is OrderStatus.ROLLED_BACK
    assert cycle.visit_id is None
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.visit_id is None
    assert restored.status is OrderStatus.ROLLED_BACK


def test_closed_order_blocks_second_open_same_operational_day() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=_SHELF_BEFORE,
    )
    cycle.close(at=_AT)
    with pytest.raises(SecondCommandRejected):
        _open(cycle, at=_AT, order_id="order-2")
    next_day = datetime(2026, 9, 25, 10, 0, tzinfo=_TZ)
    _open(cycle, at=next_day, order_id="order-2")
    assert cycle.order_id == "order-2"


def test_draft_after_closed_resets_status_but_keeps_same_day_reopen_block() -> None:
    """happy: DraftSaved после closed → status None; open в тот же день rejected."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=_SHELF_BEFORE,
    )
    cycle.close(at=_AT)
    assert cycle.status is OrderStatus.CLOSED
    edited = DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("3"),
    )
    cycle.save_draft((edited,))
    assert cycle.status is None
    assert cycle.order_id is None
    assert cycle.move_id is None
    assert cycle.lines[0].launch_qty == Decimal("3")
    with pytest.raises(SecondCommandRejected):
        _open(cycle, at=_AT, order_id="order-2")
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.status is None
    assert restored.lines[0].launch_qty == Decimal("3")
    with pytest.raises(SecondCommandRejected):
        _open(restored, at=_AT, order_id="order-3")


def test_repair_move_id_updates_open_cycle() -> None:
    cycle = MicromarketLoadingCycle(machine_code="704")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.pull_events()
    cycle.repair_move_id(move_id="move-repaired")
    assert cycle.move_id == "move-repaired"
    assert cycle.status is OrderStatus.OPEN
    pending = cycle.pull_events()
    assert len(pending) == 1
    assert type(pending[0]).__name__ == "OrderMoveRepaired"


def test_draft_after_rolled_back_clears_order_and_move_ids() -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    assert cycle.move_id is not None
    cycle.roll_back(at=_AT)
    cycle.save_draft((_line(),))
    assert cycle.status is None
    assert cycle.order_id is None
    assert cycle.move_id is None


def test_record_alert_is_idempotent_per_order_day() -> None:
    from datetime import date

    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.pull_events()
    day = date(2026, 9, 24)
    cycle.record_alert(order_id="order-1", operational_day=day)
    assert cycle.was_alerted(order_id="order-1", operational_day=day)
    first = cycle.pull_events()
    assert len(first) == 1
    cycle.record_alert(order_id="order-1", operational_day=day)
    assert cycle.pull_events() == ()


def test_mark_recounted_stores_shelf_before_and_deltas() -> None:
    """happy: open→recounted keeps shelf_before baseline with deltas."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    assert cycle.shelf_before is None
    deltas = (("2311", Decimal("1")),)
    cycle.mark_recounted(at=_AT, deltas=deltas, shelf_before=_SHELF_BEFORE)
    assert cycle.status is OrderStatus.RECOUNTED
    assert cycle.deltas == deltas
    assert cycle.shelf_before == _SHELF_BEFORE
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.status is OrderStatus.RECOUNTED
    assert restored.shelf_before == _SHELF_BEFORE
    assert restored.deltas == deltas


def test_replace_recount_deltas_updates_deltas_keeps_baseline() -> None:
    """happy: replace on recounted updates deltas; shelf_before unchanged."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=_SHELF_BEFORE,
    )
    new_deltas = (("2311", Decimal("-2")),)
    later = datetime(2026, 9, 24, 11, 0, tzinfo=_TZ)
    cycle.replace_recount_deltas(at=later, deltas=new_deltas)
    assert cycle.status is OrderStatus.RECOUNTED
    assert cycle.deltas == new_deltas
    assert cycle.shelf_before == _SHELF_BEFORE
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.status is OrderStatus.RECOUNTED
    assert restored.deltas == new_deltas
    assert restored.shelf_before == _SHELF_BEFORE


def test_replace_recount_deltas_rejects_without_baseline_or_not_recounted() -> None:
    """edge: replace without baseline / not recounted → ValueError."""
    open_only = MicromarketLoadingCycle(machine_code="701")
    _open(open_only, at=_AT, order_id="order-1")
    with pytest.raises(ValueError, match="recounted"):
        open_only.replace_recount_deltas(at=_AT, deltas=(("2311", Decimal("1")),))

    recounted = MicromarketLoadingCycle(machine_code="702")
    _open(recounted, at=_AT, order_id="order-2")
    recounted.status = OrderStatus.RECOUNTED
    recounted.shelf_before = None
    with pytest.raises(ValueError, match="shelf_before"):
        recounted.replace_recount_deltas(at=_AT, deltas=(("2311", Decimal("1")),))

    empty_baseline = MicromarketLoadingCycle(machine_code="703")
    _open(empty_baseline, at=_AT, order_id="order-3")
    empty_baseline.status = OrderStatus.RECOUNTED
    empty_baseline.shelf_before = ()
    with pytest.raises(ValueError, match="shelf_before"):
        empty_baseline.replace_recount_deltas(at=_AT, deltas=(("2311", Decimal("1")),))


def test_mark_recounted_rejects_when_not_open() -> None:
    """error: mark_recounted requires open order."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    with pytest.raises(ValueError, match="open"):
        cycle.mark_recounted(at=_AT, deltas=(), shelf_before=_SHELF_BEFORE)
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(at=_AT, deltas=(), shelf_before=_SHELF_BEFORE)
    with pytest.raises(ValueError, match="open"):
        cycle.mark_recounted(at=_AT, deltas=(), shelf_before=_SHELF_BEFORE)


def test_link_visit_sets_visit_id_and_rehydrates() -> None:
    """happy: open/link sets visit_id; rehydrate preserves link."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    assert cycle.visit_id is None
    cycle.link_visit("scheduled:701:2026-09-24")
    assert cycle.visit_id == "scheduled:701:2026-09-24"
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.visit_id == "scheduled:701:2026-09-24"
    assert restored.order_id == "order-1"


def test_link_visit_same_id_is_noop() -> None:
    """edge: repeat link with same visit_id is idempotent (no new event)."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.link_visit("field:701:2026-09-24")
    cycle.pull_events()
    cycle.link_visit("field:701:2026-09-24")
    assert cycle.pull_events() == ()
    assert cycle.visit_id == "field:701:2026-09-24"


def test_link_visit_rejects_different_id() -> None:
    """error: incompatible re-link raises ValueError."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.link_visit("field:701:2026-09-24")
    with pytest.raises(ValueError, match="visit_id"):
        cycle.link_visit("scheduled:701:2026-09-24")
    assert cycle.visit_id == "field:701:2026-09-24"


def test_ops_accept_applies_launch_and_closes_open_order() -> None:
    """happy: close_without_recount from open → closed with ops reason."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.close_without_recount(at=_AT)
    assert cycle.status is OrderStatus.CLOSED
    assert cycle.close_kind == OPS_CONFIRMED_WITHOUT_RECOUNT
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=cycle.pull_events(),
    )
    assert restored.status is OrderStatus.CLOSED
    assert restored.close_kind == OPS_CONFIRMED_WITHOUT_RECOUNT


def test_legacy_close_from_open_still_rejected() -> None:
    """error: legacy close still requires recounted."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    with pytest.raises(ValueError, match="recounted"):
        cycle.close(at=_AT)
    assert cycle.status is OrderStatus.OPEN


def test_close_without_recount_idempotent() -> None:
    """edge: second close_without_recount is noop."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.close_without_recount(at=_AT)
    cycle.pull_events()
    cycle.close_without_recount(at=_AT)
    assert cycle.pull_events() == ()
    assert cycle.status is OrderStatus.CLOSED


def test_close_without_recount_rejects_recounted() -> None:
    """error: cannot ops-close from recounted."""
    cycle = MicromarketLoadingCycle(machine_code="701")
    _open(cycle, at=_AT, order_id="order-1")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=_SHELF_BEFORE,
    )
    with pytest.raises(ValueError, match="open order"):
        cycle.close_without_recount(at=_AT)
    assert cycle.status is OrderStatus.RECOUNTED
