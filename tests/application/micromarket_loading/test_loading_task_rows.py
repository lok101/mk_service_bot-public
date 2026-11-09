from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.loading_task_rows import project_loading_task_rows
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus

_TZ = ZoneInfo("Europe/Moscow")
_AT = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)


def _line() -> DraftLine:
    return DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )


def _open(machine_code: str, *, order_id: str) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=machine_code)
    cycle.open_order(
        order_id=order_id,
        move_id=f"move-{order_id}",
        lines=(_line(),),
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    return cycle


def test_loading_task_row_after_launch_in_feed() -> None:
    cycle = _open("701", order_id="order-1")
    cycle.link_visit("scheduled:701:2026-09-24")
    rows = project_loading_task_rows((cycle,), timezone=_TZ)
    assert len(rows) == 1
    row = rows[0]
    assert row.machine_code == "701"
    assert row.status is OrderStatus.OPEN
    assert row.trigger_label == "Загрузка"
    assert row.status_label == "открыта"
    assert row.order_id == "order-1"
    assert row.visit_id == "scheduled:701:2026-09-24"
    park = project_loading_task_rows((cycle,), timezone=_TZ)
    machine = project_loading_task_rows((cycle,), machine_code="701", timezone=_TZ)
    assert len(park) == 1
    assert len(machine) == 1
    assert project_loading_task_rows((cycle,), machine_code="999", timezone=_TZ) == ()


def test_publish_journal_rows_still_rendered() -> None:
    """Anchor name: loading projection is additive; draft-only cycles stay hidden."""
    draft = MicromarketLoadingCycle(machine_code="701")
    draft.save_draft((_line(),))
    assert project_loading_task_rows((draft,), timezone=_TZ) == ()


def test_rolled_back_row_status() -> None:
    cycle = _open("701", order_id="order-1")
    cycle.roll_back(at=_AT)
    rows = project_loading_task_rows((cycle,), timezone=_TZ)
    assert len(rows) == 1
    assert rows[0].status is OrderStatus.ROLLED_BACK
    assert rows[0].status_label == "откат"
    assert rows[0].visit_id is None
