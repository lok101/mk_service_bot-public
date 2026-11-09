from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.move_gateway import MoveAlreadyGone
from src.application.micromarket_loading.rollback_loading import (
    RollbackMicromarketLoading,
    RollbackNotAllowed,
)
from src.application.micromarket_loading.save_draft import SaveMicromarketLoadingDraft
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_TZ = ZoneInfo("Europe/Moscow")
_HOUR = 6
_AT = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _FakeGateway:
    def __init__(self) -> None:
        self.delete_calls: list[str] = []

    def warehouse_qty(self, product_code: str) -> Decimal:
        return Decimal("10")

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return {code: Decimal("10") for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        return f"move-{order_id}"

    def delete_move(self, *, move_id: str) -> None:
        self.delete_calls.append(move_id)

    def move_moment(self, *, move_id: str) -> datetime | None:
        return getattr(self, "moments", {}).get(move_id)

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        del order_id, now
        return False


@dataclass
class _RecordingDetach:
    calls: list[tuple[str, datetime, str | None]] = field(default_factory=list)

    def detach(
        self,
        *,
        machine_code: str,
        at: datetime,
        visit_id: str | None,
    ) -> None:
        self.calls.append((machine_code, at, visit_id))


def _open_linked(cycle_store: _MemoryCycleStore, *, visit_id: str) -> None:
    SaveMicromarketLoadingDraft(cycle_store=cycle_store).execute(
        machine_code="701",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
    )
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.open_order(
        order_id="order-1",
        move_id="move-order-1",
        lines=cycle.lines,
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )
    cycle.link_visit(visit_id)
    cycle_store.save(cycle)


def test_rollback_clears_loading_only_visit_task() -> None:
    """happy: successful rollback calls detach with prior visit_id and unlinks cycle."""
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway()
    detach = _RecordingDetach()
    _open_linked(cycle_store, visit_id="scheduled:701:2026-09-24")

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=gateway,
        clock=lambda: _AT,
        detach_visit=detach,
    ).execute(machine_code="701")

    assert result is None
    rolled = cycle_store.load("701")
    assert rolled is not None
    assert rolled.status is OrderStatus.ROLLED_BACK
    assert rolled.visit_id is None
    assert detach.calls == [("701", _AT, "scheduled:701:2026-09-24")]


def test_rollback_keeps_visit_when_other_sources() -> None:
    """Contract: rollback still passes visit_id to detach; UC decides keep vs clear."""
    cycle_store = _MemoryCycleStore()
    detach = _RecordingDetach()
    _open_linked(cycle_store, visit_id="scheduled:701:2026-09-24")

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=_FakeGateway(),
        clock=lambda: _AT,
        detach_visit=detach,
    ).execute(machine_code="701")

    assert result is None
    assert detach.calls[0][2] == "scheduled:701:2026-09-24"


def test_rollback_rejected_does_not_detach() -> None:
    cycle_store = _MemoryCycleStore()
    detach = _RecordingDetach()
    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=_FakeGateway(),
        clock=lambda: _AT,
        detach_visit=detach,
    ).execute(machine_code="701")
    assert isinstance(result, RollbackNotAllowed)
    assert detach.calls == []


def test_rollback_without_visit_id_still_detaches_noop_args() -> None:
    cycle_store = _MemoryCycleStore()
    SaveMicromarketLoadingDraft(cycle_store=cycle_store).execute(
        machine_code="701",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
    )
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.open_order(
        order_id="order-1",
        move_id="move-order-1",
        lines=cycle.lines,
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )
    cycle_store.save(cycle)
    detach = _RecordingDetach()

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=_FakeGateway(),
        clock=lambda: _AT,
        detach_visit=detach,
    ).execute(machine_code="701")

    assert result is None
    assert detach.calls == [("701", _AT, None)]


def test_rollback_treats_missing_move_as_removed_and_detaches() -> None:
    class _GoneGateway(_FakeGateway):
        def delete_move(self, *, move_id: str) -> None:
            self.delete_calls.append(move_id)
            raise MoveAlreadyGone(move_id)

    cycle_store = _MemoryCycleStore()
    detach = _RecordingDetach()
    _open_linked(cycle_store, visit_id="scheduled:701:2026-09-24")
    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=_GoneGateway(),
        clock=lambda: _AT,
        detach_visit=detach,
    ).execute(machine_code="701")
    assert result is None
    assert len(detach.calls) == 1


def test_rollback_restores_warehouse_snapshot_qty() -> None:
    """happy: after successful delete_move apply_delta(+) for launched lines."""
    cycle_store = _MemoryCycleStore()
    snapshot = InMemoryMicromarketWarehouseStockSnapshotStore()
    snapshot.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            refreshed_at=_AT,
            qty_by_catalog_code={"2311": Decimal("3")},
        ),
    )
    _open_linked(cycle_store, visit_id="scheduled:701:2026-09-24")

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=_FakeGateway(),
        clock=lambda: _AT,
        warehouse_stock=snapshot,
    ).execute(machine_code="701")

    assert result is None
    loaded = snapshot.get()
    assert loaded is not None
    assert loaded.qty_by_catalog_code["2311"] == Decimal("5")


def test_rollback_skips_delete_when_ms_move_predates_open() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway()
    gateway.moments = {"move-order-1": datetime(2026, 9, 24, 8, 0, tzinfo=_TZ)}
    _open_linked(cycle_store, visit_id="scheduled:701:2026-09-24")
    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=gateway,
        clock=lambda: _AT,
    ).execute(machine_code="701")
    assert result is None
    assert gateway.delete_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.ROLLED_BACK
