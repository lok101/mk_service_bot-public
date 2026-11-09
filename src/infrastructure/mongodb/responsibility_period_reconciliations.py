from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.inventory_reconciliation import PeriodReconciliationNotFound
from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.coverage import ReconciliationStatus
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import (
    FrozenLoadLine,
    FrozenSalesLine,
    ResponsibilityPeriodReconciliation,
)
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class PeriodReconciliationsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> Any: ...

    def update_many(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def distinct(self, key: str, filter: dict[str, Any]) -> list[Any]: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...

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
def _reconciliation_line_to_document(line: ReconciliationLine) -> dict[str, str]:
    return {
        "product_code": line.product_code,
        "actual_prev": _decimal_to_str(line.actual_prev),
        "actual": _decimal_to_str(line.actual),
        "calculated": _decimal_to_str(line.calculated),
        "delta": _decimal_to_str(line.delta),
        "loads_total": _decimal_to_str(line.loads_total),
        "sales_total": _decimal_to_str(line.sales_total),
    }


@beartype
def _reconciliation_line_from_document(document: dict[str, Any]) -> ReconciliationLine:
    product_code = document.get("product_code")
    if not isinstance(product_code, str):
        raise ValueError("line.product_code must be a string")
    return ReconciliationLine(
        product_code=product_code,
        actual_prev=_decimal_from_document(document.get("actual_prev")),
        actual=_decimal_from_document(document.get("actual")),
        calculated=_decimal_from_document(document.get("calculated")),
        delta=_decimal_from_document(document.get("delta")),
        loads_total=_decimal_from_document(document.get("loads_total", "0")),
        sales_total=_decimal_from_document(document.get("sales_total", "0")),
    )


@beartype
def _frozen_load_line_to_document(line: FrozenLoadLine) -> dict[str, Any]:
    return {
        "product_code": line.product_code,
        "occurred_at": _as_utc(line.occurred_at),
        "input_quantity": _decimal_to_str(line.input_quantity),
        "input_unit": line.input_unit,
        "pack_size": _decimal_to_str(line.pack_size),
        "base_quantity": _decimal_to_str(line.base_quantity),
        "loading_event_id": line.loading_event_id,
    }


@beartype
def _frozen_load_line_from_document(document: dict[str, Any]) -> FrozenLoadLine:
    product_code = document.get("product_code")
    occurred_at = document.get("occurred_at")
    input_unit = document.get("input_unit")
    loading_event_id = document.get("loading_event_id")
    if (
        not isinstance(product_code, str)
        or not isinstance(occurred_at, datetime)
        or input_unit != "package"
        or not isinstance(loading_event_id, str)
    ):
        raise ValueError("load line document has invalid shape")
    return FrozenLoadLine(
        product_code=product_code,
        occurred_at=_as_utc(occurred_at),
        input_quantity=_decimal_from_document(document.get("input_quantity")),
        input_unit="package",
        pack_size=_decimal_from_document(document.get("pack_size")),
        base_quantity=_decimal_from_document(document.get("base_quantity")),
        loading_event_id=loading_event_id,
    )


@beartype
def _frozen_sales_line_to_document(line: FrozenSalesLine) -> dict[str, Any]:
    return {
        "product_code": line.product_code,
        "quantity": _decimal_to_str(line.quantity),
        "occurred_at": _as_utc(line.occurred_at),
        "source_id": line.source_id,
    }


@beartype
def _frozen_sales_line_from_document(document: dict[str, Any]) -> FrozenSalesLine:
    product_code = document.get("product_code")
    source_id = document.get("source_id")
    occurred_at = document.get("occurred_at")
    if (
        not isinstance(product_code, str)
        or not isinstance(source_id, str)
        or not isinstance(occurred_at, datetime)
    ):
        raise ValueError("sales line document has invalid shape")
    return FrozenSalesLine(
        product_code=product_code,
        quantity=_decimal_from_document(document.get("quantity")),
        occurred_at=_as_utc(occurred_at),
        source_id=source_id,
    )


@beartype
def snapshot_to_document(snapshot: ResponsibilityPeriodReconciliation) -> dict[str, Any]:
    return {
        "period_id": snapshot.period_id,
        "machine_id": snapshot.machine_id.value,
        "responsible_technician_id": snapshot.responsible_technician_id.value,
        "opening_revision_id": snapshot.opening_revision_id.value,
        "closing_revision_id": snapshot.closing_revision_id.value,
        "opened_at": _as_utc(snapshot.opened_at),
        "closed_at": _as_utc(snapshot.closed_at),
        "lines": [_reconciliation_line_to_document(line) for line in snapshot.lines],
        "sales_lines": [_frozen_sales_line_to_document(line) for line in snapshot.sales_lines],
        "load_lines": [_frozen_load_line_to_document(line) for line in snapshot.load_lines],
        "load_count": snapshot.load_count,
        "status": snapshot.status,
        "calculated_source": snapshot.calculated_source,
        "ledger_posted": snapshot.ledger_posted,
        "reconciled": snapshot.reconciled,
        "location_name": snapshot.location_name,
        "technician_name": snapshot.technician_name,
    }


@beartype
def snapshot_from_document(document: dict[str, Any]) -> ResponsibilityPeriodReconciliation:
    period_id = document.get("period_id")
    machine_id = document.get("machine_id")
    responsible_technician_id = document.get("responsible_technician_id")
    opening_revision_id = document.get("opening_revision_id")
    closing_revision_id = document.get("closing_revision_id")
    opened_at = document.get("opened_at")
    closed_at = document.get("closed_at")
    lines_raw = document.get("lines")
    sales_lines_raw = document.get("sales_lines")
    load_lines_raw = document.get("load_lines", ())
    load_count = document.get("load_count")
    status = document.get("status")
    calculated_source = document.get("calculated_source", "domain")
    ledger_posted = document.get("ledger_posted", False)
    reconciled = document.get("reconciled", False)
    location_name_raw = document.get("location_name", "")
    technician_name_raw = document.get("technician_name", "")
    if location_name_raw is None:
        location_name = ""
    elif isinstance(location_name_raw, str):
        location_name = location_name_raw
    else:
        raise ValueError("Responsibility period reconciliation document has invalid shape")
    if technician_name_raw is None:
        technician_name = ""
    elif isinstance(technician_name_raw, str):
        technician_name = technician_name_raw
    else:
        raise ValueError("Responsibility period reconciliation document has invalid shape")
    if (
        not isinstance(period_id, str)
        or not isinstance(machine_id, str)
        or not isinstance(responsible_technician_id, str)
        or not isinstance(opening_revision_id, str)
        or not isinstance(closing_revision_id, str)
        or not isinstance(opened_at, datetime)
        or not isinstance(closed_at, datetime)
        or not isinstance(lines_raw, list)
        or not isinstance(sales_lines_raw, list)
        or not isinstance(load_count, int)
        or status not in ("complete", "pending_sales")
        or calculated_source != "domain"
        or not isinstance(ledger_posted, bool)
        or not isinstance(reconciled, bool)
    ):
        raise ValueError("Responsibility period reconciliation document has invalid shape")
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId(machine_id),
        responsible_technician_id=TechnicianId(responsible_technician_id),
        opening_revision_id=RevisionId(opening_revision_id),
        closing_revision_id=RevisionId(closing_revision_id),
        opened_at=_as_utc(opened_at),
        closed_at=_as_utc(closed_at),
        lines=tuple(
            _reconciliation_line_from_document(line) for line in lines_raw if isinstance(line, dict)
        ),
        sales_lines=tuple(
            _frozen_sales_line_from_document(line)
            for line in sales_lines_raw
            if isinstance(line, dict)
        ),
        load_lines=tuple(
            _frozen_load_line_from_document(line)
            for line in load_lines_raw
            if isinstance(line, dict)
        )
        if isinstance(load_lines_raw, list)
        else (),
        load_count=load_count,
        status=status,
        calculated_source="domain",
        ledger_posted=ledger_posted,
        reconciled=reconciled,
        location_name=location_name,
        technician_name=technician_name,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoPeriodReconciliationRepository(ResponsibilityPeriodReconciliationRepository):
    _collection: PeriodReconciliationsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: PeriodReconciliationsCollection,
    ) -> MongoPeriodReconciliationRepository:
        repo = cls(_collection=collection)
        repo.ensure_indexes()
        return repo

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoPeriodReconciliationRepository:
        collection = resolve_collection(
            settings,
            collection_name=settings.responsibility_period_reconciliations_collection,
            owner="MongoPeriodReconciliationRepository",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            "period_id",
            unique=True,
            name="period_reconciliation_period_id_unique",
        )
        self._collection.create_index(
            [
                ("responsible_technician_id", ASCENDING),
                ("status", ASCENDING),
                ("ledger_posted", ASCENDING),
                ("reconciled", ASCENDING),
            ],
            name="period_reconciliation_tech_status_flags",
        )
        self._collection.create_index(
            [
                ("machine_id", ASCENDING),
                ("opening_revision_id", ASCENDING),
            ],
            name="period_reconciliation_machine_opening_revision",
        )

    @beartype
    def save(self, snapshot: ResponsibilityPeriodReconciliation) -> None:
        self._collection.replace_one(
            {"period_id": snapshot.period_id},
            snapshot_to_document(snapshot),
            upsert=True,
        )

    @beartype
    def get_by_period_id(self, period_id: str) -> ResponsibilityPeriodReconciliation | None:
        document = self._collection.find_one({"period_id": period_id})
        if document is None:
            return None
        return snapshot_from_document(document)

    @beartype
    def get_by_opening_revision(
        self,
        machine_id: MachineId,
        opening_revision_id: RevisionId,
    ) -> ResponsibilityPeriodReconciliation | None:
        document = self._collection.find_one(
            {
                "machine_id": machine_id.value,
                "opening_revision_id": opening_revision_id.value,
            },
        )
        if document is None:
            return None
        return snapshot_from_document(document)

    @beartype
    def list_complete_unposted(
        self,
        *,
        technician_id: TechnicianId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]:
        query: dict[str, Any] = {"status": "complete", "ledger_posted": False}
        if technician_id is not None:
            query["responsible_technician_id"] = technician_id.value
        cursor = self._collection.find(query)
        return [snapshot_from_document(document) for document in cursor]

    @beartype
    def list_by_status(
        self,
        *,
        status: ReconciliationStatus,
        machine_id: MachineId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]:
        query: dict[str, Any] = {"status": status}
        if machine_id is not None:
            query["machine_id"] = machine_id.value
        cursor = self._collection.find(query)
        return [snapshot_from_document(document) for document in cursor]

    @beartype
    def list_posted_unreconciled(
        self,
        *,
        technician_id: TechnicianId,
    ) -> list[ResponsibilityPeriodReconciliation]:
        query: dict[str, Any] = {
            "status": "complete",
            "ledger_posted": True,
            "reconciled": False,
            "responsible_technician_id": technician_id.value,
        }
        cursor = self._collection.find(query)
        return [snapshot_from_document(document) for document in cursor]

    @beartype
    def list_unreconciled_technician_ids(self) -> tuple[TechnicianId, ...]:
        raw_ids = self._collection.distinct(
            "responsible_technician_id",
            {
                "status": "complete",
                "ledger_posted": True,
                "reconciled": False,
            },
        )
        return tuple(TechnicianId(str(technician_id)) for technician_id in sorted(raw_ids))

    @beartype
    def list_reconciliation_preview_technician_ids(self) -> tuple[TechnicianId, ...]:
        posted_ids = self._collection.distinct(
            "responsible_technician_id",
            {"status": "complete", "ledger_posted": True, "reconciled": False},
        )
        pending_ids = self._collection.distinct(
            "responsible_technician_id",
            {"status": "pending_sales"},
        )
        union = sorted({str(t) for t in posted_ids} | {str(t) for t in pending_ids})
        return tuple(TechnicianId(t) for t in union)

    @beartype
    def mark_ledger_posted(self, period_id: str) -> None:
        if self.get_by_period_id(period_id) is None:
            raise PeriodReconciliationNotFound(period_id=period_id)
        self._collection.update_one(
            {"period_id": period_id},
            {"$set": {"ledger_posted": True}},
        )

    @beartype
    def mark_reconciled(self, period_ids: tuple[str, ...]) -> None:
        if not period_ids:
            return
        for period_id in period_ids:
            if self.get_by_period_id(period_id) is None:
                raise PeriodReconciliationNotFound(period_id=period_id)
        self._collection.update_many(
            {"period_id": {"$in": list(period_ids)}},
            {"$set": {"reconciled": True}},
        )

    @beartype
    def count_ledger_posted(self) -> int:
        return int(self._collection.count_documents({"ledger_posted": True}))

    @beartype
    def count_all(self) -> int:
        return int(self._collection.count_documents({}))

    @beartype
    def delete_all(self) -> int:
        result = self._collection.delete_many({})
        return int(getattr(result, "deleted_count", 0))
