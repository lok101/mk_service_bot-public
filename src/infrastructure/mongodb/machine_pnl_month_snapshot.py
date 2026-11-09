from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.machine_pnl import MonthPnlSnapshot, PnlWarning
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.config.machine_pnl_month import MachinePnlMonthSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class MonthPnlSnapshotCollection(Protocol):
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
def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@beartype
def _date_from_document(value: object) -> date:
    if isinstance(value, datetime):
        return _as_utc(value).date()
    if isinstance(value, date):
        return value
    raise ValueError("date field must be datetime or date")


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
def _opex_breakdown_to_document(
    breakdown: tuple[tuple[str, Decimal | None], ...],
) -> list[list[str | None]]:
    return [[key, None if amount is None else _decimal_to_str(amount)] for key, amount in breakdown]


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
def month_pnl_snapshot_to_document(snapshot: MonthPnlSnapshot) -> dict[str, Any]:
    return {
        "machine_id": snapshot.machine_id.value,
        "location_id": snapshot.location_id,
        "technician_id": snapshot.technician_id,
        "period_start": _date_to_utc_midnight(snapshot.period_start),
        "period_end": _date_to_utc_midnight(snapshot.period_end),
        "revenue": _decimal_to_str(snapshot.revenue),
        "revenue_known_as_of": _date_to_utc_midnight(snapshot.revenue_known_as_of),
        "cogs_expected": _decimal_to_str(snapshot.cogs_expected),
        "cogs_actual_fact": _decimal_to_str(snapshot.cogs_actual_fact),
        "cogs_actual_estimate": _decimal_to_str(snapshot.cogs_actual_estimate),
        "allocated_shortage_fact": _decimal_to_str(snapshot.allocated_shortage_fact),
        "allocated_shortage_estimate": _decimal_to_str(snapshot.allocated_shortage_estimate),
        "allocated_surplus_fact": _decimal_to_str(snapshot.allocated_surplus_fact),
        "allocated_surplus_estimate": _decimal_to_str(snapshot.allocated_surplus_estimate),
        "opex_breakdown": _opex_breakdown_to_document(snapshot.opex_breakdown),
        "opex_known_total": _decimal_to_str(snapshot.opex_known_total),
        "net_theory": _decimal_to_str(snapshot.net_theory),
        "machine_gap": _decimal_to_str(snapshot.machine_gap),
        "net_machine": _decimal_to_str(snapshot.net_machine),
        "tech_gap": _decimal_to_str(snapshot.tech_gap),
        "net_after_tech": _decimal_to_str(snapshot.net_after_tech),
        "coverage_days": snapshot.coverage_days,
        "days_in_month": snapshot.days_in_month,
        "coverage_pct": _decimal_to_str(snapshot.coverage_pct),
        "projection_basis": snapshot.projection_basis,
        "warnings": [_warning_to_document(warning) for warning in snapshot.warnings],
        "last_recomputed_at": _as_utc(snapshot.last_recomputed_at),
        "company_id": snapshot.company_id,
    }


@beartype
def month_pnl_snapshot_from_document(document: dict[str, Any]) -> MonthPnlSnapshot:
    machine_id = document.get("machine_id")
    period_start = document.get("period_start")
    period_end = document.get("period_end")
    revenue_known_as_of = document.get("revenue_known_as_of")
    last_recomputed_at = document.get("last_recomputed_at")
    warnings_raw = document.get("warnings")
    coverage_days = document.get("coverage_days")
    days_in_month = document.get("days_in_month")
    projection_basis = document.get("projection_basis")
    if (
        not isinstance(machine_id, str)
        or not isinstance(period_start, datetime | date)
        or not isinstance(period_end, datetime | date)
        or not isinstance(revenue_known_as_of, datetime | date)
        or not isinstance(last_recomputed_at, datetime)
        or not isinstance(warnings_raw, list)
        or not isinstance(coverage_days, int)
        or not isinstance(days_in_month, int)
        or not isinstance(projection_basis, str)
    ):
        raise ValueError("MonthPnlSnapshot document has invalid shape")

    location_raw = document.get("location_id")
    technician_raw = document.get("technician_id")
    company_raw = document.get("company_id")
    location_id = location_raw if isinstance(location_raw, str) else None
    technician_id = technician_raw if isinstance(technician_raw, str) else None
    company_id = company_raw if isinstance(company_raw, int) else None

    return MonthPnlSnapshot(
        machine_id=MachineId(machine_id),
        location_id=location_id,
        technician_id=technician_id,
        period_start=_date_from_document(period_start),
        period_end=_date_from_document(period_end),
        revenue=_decimal_from_document(document.get("revenue")),
        revenue_known_as_of=_date_from_document(revenue_known_as_of),
        cogs_expected=_decimal_from_document(document.get("cogs_expected")),
        cogs_actual_fact=_decimal_from_document(document.get("cogs_actual_fact")),
        cogs_actual_estimate=_decimal_from_document(document.get("cogs_actual_estimate")),
        allocated_shortage_fact=_decimal_from_document(document.get("allocated_shortage_fact")),
        allocated_shortage_estimate=_decimal_from_document(
            document.get("allocated_shortage_estimate"),
        ),
        allocated_surplus_fact=_decimal_from_document(document.get("allocated_surplus_fact")),
        allocated_surplus_estimate=_decimal_from_document(
            document.get("allocated_surplus_estimate"),
        ),
        opex_breakdown=_opex_breakdown_from_document(document.get("opex_breakdown")),
        opex_known_total=_decimal_from_document(document.get("opex_known_total")),
        net_theory=_decimal_from_document(document.get("net_theory")),
        machine_gap=_decimal_from_document(document.get("machine_gap")),
        net_machine=_decimal_from_document(document.get("net_machine")),
        tech_gap=_decimal_from_document(document.get("tech_gap")),
        net_after_tech=_decimal_from_document(document.get("net_after_tech")),
        coverage_days=coverage_days,
        days_in_month=days_in_month,
        coverage_pct=_decimal_from_document(document.get("coverage_pct")),
        projection_basis=projection_basis,
        warnings=tuple(
            _warning_from_document(item) for item in warnings_raw if isinstance(item, dict)
        ),
        last_recomputed_at=_as_utc(last_recomputed_at),
        company_id=company_id,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMonthPnlSnapshotStore:
    _collection: MonthPnlSnapshotCollection

    @classmethod
    @beartype
    def from_collection(cls, collection: MonthPnlSnapshotCollection) -> MongoMonthPnlSnapshotStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        month_settings: MachinePnlMonthSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMonthPnlSnapshotStore:
        collection = resolve_collection(
            mongo,
            collection_name=month_settings.snapshot_collection,
            owner="MongoMonthPnlSnapshotStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_id", ASCENDING), ("period_start", ASCENDING)],
            unique=True,
            name="machine_pnl_month_snapshot_unique",
        )

    @beartype
    def upsert(self, snapshot: MonthPnlSnapshot) -> None:
        document = month_pnl_snapshot_to_document(snapshot)
        self._collection.replace_one(
            {
                "machine_id": snapshot.machine_id.value,
                "period_start": _date_to_utc_midnight(snapshot.period_start),
            },
            document,
            upsert=True,
        )

    @beartype
    def get(self, machine_id: MachineId, period_start: date) -> MonthPnlSnapshot | None:
        document = self._collection.find_one(
            {
                "machine_id": machine_id.value,
                "period_start": _date_to_utc_midnight(period_start),
            }
        )
        if document is None:
            return None
        return month_pnl_snapshot_from_document(document)

    @beartype
    def list_for_period_starts(
        self,
        period_starts: Sequence[date],
    ) -> tuple[MonthPnlSnapshot, ...]:
        starts = tuple(period_starts)
        if not starts:
            return ()
        documents = self._collection.find(
            {"period_start": {"$in": [_date_to_utc_midnight(item) for item in starts]}}
        )
        snapshots: list[MonthPnlSnapshot] = []
        for document in documents:
            if isinstance(document, dict):
                snapshots.append(month_pnl_snapshot_from_document(document))
        return tuple(snapshots)
