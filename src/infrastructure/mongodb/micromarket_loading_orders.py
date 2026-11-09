from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from src.domain.micromarket_loading.errors import MicromarketLoadingConcurrencyError
from src.domain.micromarket_loading.order import MicromarketLoadingCycle
from src.domain.micromarket_loading.order_events import (
    DraftLine,
    DraftSaved,
    MicromarketLoadingCycleEvent,
    OrderAlertRecorded,
    OrderClosed,
    OrderLaunchIntended,
    OrderMoveRepaired,
    OrderOpened,
    OrderRecounted,
    OrderRecountReplaced,
    OrderRolledBack,
    OrderVisitLinked,
)

_EVENT_TYPE_DRAFT_SAVED = "DraftSaved"
_EVENT_TYPE_ORDER_LAUNCH_INTENDED = "OrderLaunchIntended"
_EVENT_TYPE_ORDER_OPENED = "OrderOpened"
_EVENT_TYPE_ORDER_RECOUNTED = "OrderRecounted"
_EVENT_TYPE_ORDER_RECOUNT_REPLACED = "OrderRecountReplaced"
_EVENT_TYPE_ORDER_CLOSED = "OrderClosed"
_EVENT_TYPE_ORDER_ROLLED_BACK = "OrderRolledBack"
_EVENT_TYPE_ORDER_ALERT_RECORDED = "OrderAlertRecorded"
_EVENT_TYPE_ORDER_VISIT_LINKED = "OrderVisitLinked"
_EVENT_TYPE_ORDER_MOVE_REPAIRED = "OrderMoveRepaired"


@runtime_checkable
class MicromarketLoadingOrderEventsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _draft_lines_to_list(lines: tuple[DraftLine, ...]) -> list[dict[str, object]]:
    return [
        {
            "product_code": line.product_code,
            "target_qty": line.target_qty,
            "stock_qty": format(line.stock_qty, "f"),
            "need_qty": format(line.need_qty, "f"),
            "launch_qty": format(line.launch_qty, "f"),
        }
        for line in lines
    ]


@beartype
def _draft_lines_from_list(value: object) -> tuple[DraftLine, ...]:
    if not isinstance(value, list):
        raise ValueError("draft lines must be a list")
    parsed: list[DraftLine] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("draft line must be a dict")
        product_code = item["product_code"]
        target_qty = item["target_qty"]
        if not isinstance(product_code, str) or not isinstance(target_qty, int):
            raise ValueError("draft line product_code/target_qty invalid")
        parsed.append(
            DraftLine(
                product_code=product_code,
                target_qty=target_qty,
                stock_qty=Decimal(str(item["stock_qty"])),
                need_qty=Decimal(str(item["need_qty"])),
                launch_qty=Decimal(str(item["launch_qty"])),
            ),
        )
    return tuple(parsed)


@beartype
def _deltas_to_list(deltas: tuple[tuple[str, Decimal], ...]) -> list[dict[str, object]]:
    return [{"product_code": code, "quantity": format(qty, "f")} for code, qty in deltas]


@beartype
def _deltas_from_list(value: object) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError("deltas must be a list")
    parsed: list[tuple[str, Decimal]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("delta item must be a dict")
        product_code = item["product_code"]
        if not isinstance(product_code, str):
            raise ValueError("delta product_code must be str")
        parsed.append((product_code, Decimal(str(item["quantity"]))))
    return tuple(parsed)


@beartype
def micromarket_loading_order_event_to_document(
    event: MicromarketLoadingCycleEvent,
    *,
    machine_code: str,
    stream_version: int,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "machine_code": machine_code,
        "stream_version": stream_version,
        "event_type": event.__class__.__name__,
    }
    if isinstance(event, DraftSaved):
        base["payload"] = {"lines": _draft_lines_to_list(event.lines)}
        return base
    if isinstance(event, OrderLaunchIntended):
        base["payload"] = {"order_id": event.order_id}
        return base
    if isinstance(event, OrderOpened):
        base["payload"] = {
            "order_id": event.order_id,
            "move_id": event.move_id,
            "lines": _draft_lines_to_list(event.lines),
            "opened_at": _as_utc(event.opened_at),
            "opened_operational_day": event.opened_operational_day.isoformat(),
        }
        return base
    if isinstance(event, OrderRecounted):
        payload: dict[str, object] = {
            "deltas": _deltas_to_list(event.deltas),
            "at": _as_utc(event.at),
        }
        if event.shelf_before is not None:
            payload["shelf_before"] = _deltas_to_list(event.shelf_before)
        base["payload"] = payload
        return base
    if isinstance(event, OrderRecountReplaced):
        base["payload"] = {
            "deltas": _deltas_to_list(event.deltas),
            "at": _as_utc(event.at),
        }
        return base
    if isinstance(event, OrderClosed):
        closed_payload: dict[str, Any] = {"at": _as_utc(event.at)}
        if event.close_kind is not None:
            closed_payload["close_kind"] = event.close_kind
        base["payload"] = closed_payload
        return base
    if isinstance(event, OrderRolledBack):
        base["payload"] = {"at": _as_utc(event.at)}
        return base
    if isinstance(event, OrderAlertRecorded):
        base["payload"] = {
            "order_id": event.order_id,
            "operational_day": event.operational_day.isoformat(),
        }
        return base
    if isinstance(event, OrderVisitLinked):
        base["payload"] = {"visit_id": event.visit_id}
        return base
    if isinstance(event, OrderMoveRepaired):
        base["payload"] = {"move_id": event.move_id}
        return base
    raise TypeError(f"unsupported micromarket loading order event: {type(event)!r}")


@beartype
def micromarket_loading_order_event_from_document(
    document: dict[str, Any],
) -> MicromarketLoadingCycleEvent:
    event_type = document.get("event_type")
    payload = document.get("payload")
    if not isinstance(event_type, str) or not isinstance(payload, dict):
        raise ValueError("micromarket loading order event document has invalid shape")
    if event_type == _EVENT_TYPE_DRAFT_SAVED:
        return DraftSaved(lines=_draft_lines_from_list(payload["lines"]))
    if event_type == _EVENT_TYPE_ORDER_LAUNCH_INTENDED:
        order_id = payload["order_id"]
        if not isinstance(order_id, str):
            raise ValueError("OrderLaunchIntended payload invalid")
        return OrderLaunchIntended(order_id=order_id)
    if event_type == _EVENT_TYPE_ORDER_OPENED:
        opened_at = payload["opened_at"]
        day_raw = payload["opened_operational_day"]
        order_id = payload["order_id"]
        move_id = payload["move_id"]
        if (
            not isinstance(opened_at, datetime)
            or not isinstance(day_raw, str)
            or not isinstance(order_id, str)
            or not isinstance(move_id, str)
        ):
            raise ValueError("OrderOpened payload invalid")
        return OrderOpened(
            order_id=order_id,
            move_id=move_id,
            lines=_draft_lines_from_list(payload["lines"]),
            opened_at=_as_utc(opened_at),
            opened_operational_day=date.fromisoformat(day_raw),
        )
    if event_type == _EVENT_TYPE_ORDER_RECOUNTED:
        at = payload["at"]
        if not isinstance(at, datetime):
            raise ValueError("OrderRecounted.at must be datetime")
        if "shelf_before" not in payload:
            shelf_before: tuple[tuple[str, Decimal], ...] | None = None
        else:
            shelf_before = _deltas_from_list(payload["shelf_before"])
        return OrderRecounted(
            deltas=_deltas_from_list(payload["deltas"]),
            at=_as_utc(at),
            shelf_before=shelf_before,
        )
    if event_type == _EVENT_TYPE_ORDER_RECOUNT_REPLACED:
        at = payload["at"]
        if not isinstance(at, datetime):
            raise ValueError("OrderRecountReplaced.at must be datetime")
        return OrderRecountReplaced(
            deltas=_deltas_from_list(payload["deltas"]),
            at=_as_utc(at),
        )
    if event_type == _EVENT_TYPE_ORDER_CLOSED:
        at = payload["at"]
        if not isinstance(at, datetime):
            raise ValueError("OrderClosed.at must be datetime")
        close_kind = payload.get("close_kind")
        if close_kind is not None and not isinstance(close_kind, str):
            raise ValueError("OrderClosed.close_kind must be str or absent")
        return OrderClosed(at=_as_utc(at), close_kind=close_kind)
    if event_type == _EVENT_TYPE_ORDER_ROLLED_BACK:
        at = payload["at"]
        if not isinstance(at, datetime):
            raise ValueError("OrderRolledBack.at must be datetime")
        return OrderRolledBack(at=_as_utc(at))
    if event_type == _EVENT_TYPE_ORDER_ALERT_RECORDED:
        order_id = payload["order_id"]
        day_raw = payload["operational_day"]
        if not isinstance(order_id, str) or not isinstance(day_raw, str):
            raise ValueError("OrderAlertRecorded payload invalid")
        return OrderAlertRecorded(
            order_id=order_id,
            operational_day=date.fromisoformat(day_raw),
        )
    if event_type == _EVENT_TYPE_ORDER_VISIT_LINKED:
        visit_id = payload["visit_id"]
        if not isinstance(visit_id, str):
            raise ValueError("OrderVisitLinked payload invalid")
        return OrderVisitLinked(visit_id=visit_id)
    if event_type == _EVENT_TYPE_ORDER_MOVE_REPAIRED:
        move_id = payload["move_id"]
        if not isinstance(move_id, str):
            raise ValueError("OrderMoveRepaired payload invalid")
        return OrderMoveRepaired(move_id=move_id)
    raise ValueError(f"unknown micromarket loading order event_type: {event_type!r}")


class MongoMicromarketLoadingOrderStore:
    @beartype
    def __init__(self, collection: MicromarketLoadingOrderEventsCollection) -> None:
        self._collection = collection
        self.ensure_indexes()

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_code", ASCENDING), ("stream_version", ASCENDING)],
            unique=True,
            name="micromarket_loading_order_stream_version_unique",
        )

    @beartype
    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        events = self._list_events(machine_code)
        if not events:
            return None
        return MicromarketLoadingCycle.rehydrate(machine_code=machine_code, events=events)

    @beartype
    def find_opened(self, *, machine_code: str, order_id: str) -> OrderOpened | None:
        cursor = self._collection.find(
            {
                "machine_code": machine_code,
                "event_type": _EVENT_TYPE_ORDER_OPENED,
                "payload.order_id": order_id,
            },
            sort=[("stream_version", ASCENDING)],
        )
        for document in cursor:
            event = micromarket_loading_order_event_from_document(
                cast(dict[str, Any], document),
            )
            if isinstance(event, OrderOpened):
                return event
        return None

    @beartype
    def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]:
        codes: set[str] = set()
        cursor = self._collection.find({}, sort=[("stream_version", ASCENDING)])
        for document in cursor:
            raw = cast(dict[str, Any], document).get("machine_code")
            if isinstance(raw, str):
                codes.add(raw)
        cycles: list[MicromarketLoadingCycle] = []
        for code in sorted(codes):
            cycle = self.load(code)
            if cycle is not None:
                cycles.append(cycle)
        return tuple(cycles)

    @beartype
    def save(self, cycle: MicromarketLoadingCycle) -> None:
        current = self._collection.count_documents({"machine_code": cycle.machine_code})
        if current != cycle.loaded_version:
            raise MicromarketLoadingConcurrencyError(machine_code=cycle.machine_code)

        pending = cycle.pull_events()
        if not pending:
            return

        next_version = current
        for event in pending:
            next_version += 1
            try:
                self._collection.insert_one(
                    micromarket_loading_order_event_to_document(
                        event,
                        machine_code=cycle.machine_code,
                        stream_version=next_version,
                    ),
                )
            except DuplicateKeyError as error:
                raise MicromarketLoadingConcurrencyError(
                    machine_code=cycle.machine_code,
                ) from error
        cycle.mark_persisted(stream_version=next_version)

    @beartype
    def _list_events(self, machine_code: str) -> tuple[MicromarketLoadingCycleEvent, ...]:
        cursor = self._collection.find(
            {"machine_code": machine_code},
            sort=[("stream_version", ASCENDING)],
        )
        return tuple(
            micromarket_loading_order_event_from_document(cast(dict[str, Any], document))
            for document in cursor
        )
