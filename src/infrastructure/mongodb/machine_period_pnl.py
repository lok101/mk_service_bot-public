from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.machine_pnl import PeriodPnl, PnlWarning, make_pnl_id
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.config.machine_pnl import MachinePnlSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.connection import resolve_collection

_FULL_SLICE_KEY = "full"


@runtime_checkable
class PeriodPnlCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _decimal_to_str(value: Decimal) -> str:
    return format(value, "f")


@beartype
def _decimal_from_document(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("decimal field must be str or Decimal")


@beartype
def _warning_to_document(warning: PnlWarning) -> dict[str, str | None]:
    return {
        "code": warning.code,
        "message": warning.message,
        "sku": warning.sku,
    }


@beartype
def _warning_from_document(document: dict[str, Any]) -> PnlWarning:
    code = document.get("code")
    message = document.get("message")
    sku = document.get("sku")
    if not isinstance(code, str) or not isinstance(message, str):
        raise ValueError("warning document has invalid shape")
    if sku is not None and not isinstance(sku, str):
        raise ValueError("warning.sku must be str or None")
    return PnlWarning(code=code, message=message, sku=sku)


@beartype
def period_pnl_to_document(
    pnl: PeriodPnl,
    *,
    source_session_id: str | None,
    computed_at: datetime,
) -> dict[str, Any]:
    return {
        "pnl_id": pnl.pnl_id,
        "period_id": pnl.period_id,
        "slice_key": pnl.slice_key,
        "machine_id": pnl.machine_id.value,
        "opened_at": _as_utc(pnl.opened_at),
        "closed_at": _as_utc(pnl.closed_at),
        "revenue": _decimal_to_str(pnl.revenue),
        "cogs_expected": _decimal_to_str(pnl.cogs_expected),
        "cogs_actual": _decimal_to_str(pnl.cogs_actual),
        "allocated_shortage": _decimal_to_str(pnl.allocated_shortage),
        "allocated_surplus": _decimal_to_str(pnl.allocated_surplus),
        "opex": _decimal_to_str(pnl.opex),
        "opex_breakdown": [
            [key, None if amount is None else _decimal_to_str(amount)]
            for key, amount in pnl.opex_breakdown
        ],
        "net_before_residual": _decimal_to_str(pnl.net_before_residual),
        "net_after_shortage": _decimal_to_str(pnl.net_after_shortage),
        "warnings": [_warning_to_document(warning) for warning in pnl.warnings],
        "location_id": pnl.location_id,
        "technician_id": pnl.technician_id,
        "source_session_id": source_session_id,
        "computed_at": _as_utc(computed_at),
    }


@beartype
def _opex_breakdown_from_document(raw: object) -> tuple[tuple[str, Decimal | None], ...]:
    if raw is None:
        return empty_opex_breakdown()
    if not isinstance(raw, list):
        raise ValueError("opex_breakdown must be list or missing")
    breakdown: list[tuple[str, Decimal | None]] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ValueError("opex_breakdown item has invalid shape")
        key, amount = item
        if not isinstance(key, str):
            raise ValueError("opex_breakdown key must be str")
        if amount is None:
            breakdown.append((key, None))
        else:
            breakdown.append((key, _decimal_from_document(amount)))
    return tuple(breakdown)


@beartype
def period_pnl_from_document(document: dict[str, Any]) -> PeriodPnl:
    pnl_id = document.get("pnl_id")
    period_id = document.get("period_id")
    slice_key = document.get("slice_key")
    machine_id = document.get("machine_id")
    opened_at = document.get("opened_at")
    closed_at = document.get("closed_at")
    warnings_raw = document.get("warnings")
    if (
        not isinstance(period_id, str)
        or not isinstance(machine_id, str)
        or not isinstance(opened_at, datetime)
        or not isinstance(closed_at, datetime)
        or not isinstance(warnings_raw, list)
    ):
        raise ValueError("PeriodPnl document has invalid shape")
    if not isinstance(pnl_id, str):
        pnl_id = make_pnl_id(period_id)
    if not isinstance(slice_key, str):
        slice_key = _FULL_SLICE_KEY

    # Legacy key unallocated_residual_by_sku is ignored if present.
    warnings = tuple(
        _warning_from_document(item) for item in warnings_raw if isinstance(item, dict)
    )
    location_raw = document.get("location_id")
    technician_raw = document.get("technician_id")
    location_id = location_raw if isinstance(location_raw, str) else None
    technician_id = technician_raw if isinstance(technician_raw, str) else None

    return PeriodPnl(
        pnl_id=pnl_id,
        period_id=period_id,
        slice_key=slice_key,
        machine_id=MachineId(machine_id),
        opened_at=_as_utc(opened_at),
        closed_at=_as_utc(closed_at),
        revenue=_decimal_from_document(document.get("revenue")),
        cogs_expected=_decimal_from_document(document.get("cogs_expected")),
        cogs_actual=_decimal_from_document(document.get("cogs_actual")),
        allocated_shortage=_decimal_from_document(document.get("allocated_shortage")),
        allocated_surplus=_decimal_from_document(document.get("allocated_surplus")),
        opex=_decimal_from_document(document.get("opex")),
        opex_breakdown=_opex_breakdown_from_document(document.get("opex_breakdown")),
        net_before_residual=_decimal_from_document(document.get("net_before_residual")),
        net_after_shortage=_decimal_from_document(document.get("net_after_shortage")),
        warnings=warnings,
        location_id=location_id,
        technician_id=technician_id,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoPeriodPnlStore:
    _collection: PeriodPnlCollection

    @classmethod
    @beartype
    def from_collection(cls, collection: PeriodPnlCollection) -> MongoPeriodPnlStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        machine_pnl: MachinePnlSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoPeriodPnlStore:
        collection = resolve_collection(
            mongo,
            collection_name=machine_pnl.period_pnl_collection,
            owner="MongoPeriodPnlStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("pnl_id", ASCENDING)],
            unique=True,
            name="machine_period_pnl_pnl_id_unique",
        )
        self._collection.create_index(
            [("period_id", ASCENDING), ("slice_key", ASCENDING)],
            unique=True,
            name="machine_period_pnl_period_slice_unique",
        )
        self._collection.create_index(
            [("machine_id", ASCENDING), ("opened_at", ASCENDING), ("closed_at", ASCENDING)],
            name="machine_period_pnl_overlap",
        )

    @beartype
    def save(self, pnl: PeriodPnl, *, source_session_id: str | None) -> None:
        document = period_pnl_to_document(
            pnl,
            source_session_id=source_session_id,
            computed_at=datetime.now(UTC),
        )
        self._collection.replace_one(
            {"pnl_id": pnl.pnl_id},
            document,
            upsert=True,
        )

    @beartype
    def get(self, pnl_id: str) -> PeriodPnl | None:
        document = self._collection.find_one({"pnl_id": pnl_id})
        if document is None:
            return None
        return period_pnl_from_document(document)

    @beartype
    def list_by_period_id(self, period_id: str) -> tuple[PeriodPnl, ...]:
        return tuple(
            period_pnl_from_document(document)
            for document in self._collection.find({"period_id": period_id})
        )

    @beartype
    def list_overlapping(
        self,
        machine_id: MachineId,
        *,
        range_start: datetime,
        range_end: datetime,
    ) -> tuple[PeriodPnl, ...]:
        cursor = self._collection.find(
            {
                "machine_id": machine_id.value,
                "opened_at": {"$lt": _as_utc(range_end)},
                "closed_at": {"$gt": _as_utc(range_start)},
            }
        )
        return tuple(period_pnl_from_document(document) for document in cursor)

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[PeriodPnl, ...]:
        return tuple(
            period_pnl_from_document(document)
            for document in self._collection.find({"machine_id": machine_id.value})
        )
