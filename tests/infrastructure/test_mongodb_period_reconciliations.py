from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import mongomock
import pytest

from src.application.inventory_reconciliation.period_errors import PeriodReconciliationNotFound
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.coverage import ReconciliationStatus
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import (
    FrozenLoadLine,
    FrozenSalesLine,
    ResponsibilityPeriodReconciliation,
)
from src.infrastructure.mongodb.responsibility_period_reconciliations import (
    MongoPeriodReconciliationRepository,
    snapshot_from_document,
    snapshot_to_document,
)

_OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_TECH_A = TechnicianId("tech-a")
_MACHINE_ID = MachineId("vm-01")


def _repo() -> MongoPeriodReconciliationRepository:
    collection = mongomock.MongoClient().db.responsibility_period_reconciliations
    return MongoPeriodReconciliationRepository.from_collection(collection)


def _complete_snapshot(
    *,
    period_id: str = "rev-1:rev-2",
    technician_id: str = "tech-a",
    status: ReconciliationStatus = "complete",
    ledger_posted: bool = False,
    reconciled: bool = False,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=_MACHINE_ID,
        responsible_technician_id=TechnicianId(technician_id),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(
            ReconciliationLine(
                product_code="coffee-1",
                actual_prev=Decimal("100"),
                actual=Decimal("90"),
                calculated=Decimal("90"),
                delta=Decimal("0"),
                loads_total=Decimal("20"),
                sales_total=Decimal("30"),
            ),
        ),
        sales_lines=(
            FrozenSalesLine(
                product_code="coffee-1",
                quantity=Decimal("30"),
                occurred_at=_CLOSED,
                source_id="kv-1",
            ),
        ),
        load_count=1,
        status=status,
        ledger_posted=ledger_posted,
        reconciled=reconciled,
    )


def test_save_and_get_by_period_id_round_trip() -> None:
    repo = _repo()
    snapshot = _complete_snapshot()

    repo.save(snapshot)

    loaded = repo.get_by_period_id("rev-1:rev-2")
    assert loaded == snapshot


def test_save_and_get_round_trips_load_lines() -> None:
    repo = _repo()
    snapshot = replace(
        _complete_snapshot(),
        load_lines=(
            FrozenLoadLine(
                product_code="coffee-1",
                occurred_at=_CLOSED,
                input_quantity=Decimal("4"),
                input_unit="package",
                pack_size=Decimal("1000"),
                base_quantity=Decimal("4000"),
                loading_event_id="evt-load-1",
            ),
        ),
    )
    repo.save(snapshot)
    loaded = repo.get_by_period_id(snapshot.period_id)
    assert loaded is not None
    assert loaded.load_lines == snapshot.load_lines


def test_legacy_document_without_load_lines_defaults_empty() -> None:
    repo = _repo()
    repo._collection.insert_one(
        {
            "period_id": "legacy-load-lines",
            "machine_id": _MACHINE_ID.value,
            "responsible_technician_id": _TECH_A.value,
            "opening_revision_id": "rev-1",
            "closing_revision_id": "rev-2",
            "opened_at": _OPENED,
            "closed_at": _CLOSED,
            "lines": [],
            "sales_lines": [],
            "load_count": 0,
            "status": "complete",
            "calculated_source": "domain",
            "ledger_posted": False,
            "reconciled": False,
        },
    )
    loaded = repo.get_by_period_id("legacy-load-lines")
    assert loaded is not None
    assert loaded.load_lines == ()


def test_legacy_line_without_totals_defaults_to_zero() -> None:
    repo = _repo()
    repo._collection.insert_one(
        {
            "period_id": "legacy:period",
            "machine_id": _MACHINE_ID.value,
            "responsible_technician_id": _TECH_A.value,
            "opening_revision_id": "rev-1",
            "closing_revision_id": "rev-2",
            "opened_at": _OPENED,
            "closed_at": _CLOSED,
            "lines": [
                {
                    "product_code": "coffee-1",
                    "actual_prev": "10",
                    "actual": "9",
                    "calculated": "9",
                    "delta": "0",
                },
            ],
            "sales_lines": [],
            "load_count": 0,
            "status": "complete",
            "calculated_source": "domain",
            "ledger_posted": False,
            "reconciled": False,
        },
    )

    loaded = repo.get_by_period_id("legacy:period")
    assert loaded is not None
    line = loaded.lines[0]
    assert line.loads_total == Decimal("0")
    assert line.sales_total == Decimal("0")


def test_mark_ledger_posted_and_reconciled() -> None:
    repo = _repo()
    repo.save(_complete_snapshot(period_id="p1", technician_id="tech-a"))
    repo.mark_ledger_posted("p1")
    posted = repo.list_posted_unreconciled(technician_id=TechnicianId("tech-a"))
    assert [s.period_id for s in posted] == ["p1"]
    assert posted[0].ledger_posted is True
    assert posted[0].reconciled is False

    repo.mark_reconciled(("p1",))
    assert repo.list_posted_unreconciled(technician_id=TechnicianId("tech-a")) == []
    assert repo.count_ledger_posted() == 1


def test_list_complete_unposted_filters_by_flag() -> None:
    repo = _repo()
    repo.save(_complete_snapshot(period_id="p1", technician_id="tech-a"))
    assert [s.period_id for s in repo.list_complete_unposted()] == ["p1"]
    repo.mark_ledger_posted("p1")
    assert repo.list_complete_unposted() == []


def test_list_complete_unposted_filters_by_technician() -> None:
    repo = _repo()
    repo.save(_complete_snapshot(period_id="rev-1:rev-2", technician_id="tech-a"))
    repo.save(_complete_snapshot(period_id="rev-2:rev-3", technician_id="tech-b"))
    repo.save(_complete_snapshot(period_id="rev-3:rev-4", status="pending_sales"))
    repo.save(_complete_snapshot(period_id="rev-4:rev-5", ledger_posted=True))

    all_unposted = repo.list_complete_unposted()
    assert {snapshot.period_id for snapshot in all_unposted} == {"rev-1:rev-2", "rev-2:rev-3"}

    tech_a_only = repo.list_complete_unposted(technician_id=_TECH_A)
    assert len(tech_a_only) == 1
    assert tech_a_only[0].period_id == "rev-1:rev-2"


def test_list_by_status_filters_by_machine_id() -> None:
    repo = _repo()
    repo.save(_complete_snapshot(period_id="rev-1:rev-2"))
    repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="rev-9:rev-10",
            machine_id=MachineId("vm-02"),
            responsible_technician_id=_TECH_A,
            opening_revision_id=RevisionId("rev-9"),
            closing_revision_id=RevisionId("rev-10"),
            opened_at=_OPENED,
            closed_at=_CLOSED,
            lines=(),
            sales_lines=(),
            load_count=0,
            status="pending_sales",
        ),
    )

    pending_vm01 = repo.list_by_status(status="pending_sales", machine_id=_MACHINE_ID)
    assert pending_vm01 == []

    pending_vm02 = repo.list_by_status(status="pending_sales", machine_id=MachineId("vm-02"))
    assert len(pending_vm02) == 1
    assert pending_vm02[0].period_id == "rev-9:rev-10"


def test_mark_reconciled_raises_for_unknown_period_id() -> None:
    repo = _repo()

    with pytest.raises(PeriodReconciliationNotFound, match="rev-missing"):
        repo.mark_reconciled(("rev-missing",))


def test_mark_ledger_posted_raises_for_unknown_period_id() -> None:
    repo = _repo()

    with pytest.raises(PeriodReconciliationNotFound, match="rev-missing"):
        repo.mark_ledger_posted("rev-missing")


def test_get_by_opening_revision_returns_snapshot() -> None:
    repo = _repo()
    snapshot = ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECH_A,
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
    )
    repo.save(snapshot)

    found = repo.get_by_opening_revision(_MACHINE_ID, RevisionId("rev-1"))

    assert found is not None
    assert found.period_id == "rev-1:rev-2"


def test_get_by_opening_revision_returns_none_when_missing() -> None:
    repo = _repo()

    assert repo.get_by_opening_revision(_MACHINE_ID, RevisionId("rev-missing")) is None


def test_list_reconciliation_preview_technician_ids_union_and_sort() -> None:
    repo = _repo()
    repo.save(
        _complete_snapshot(
            period_id="a:1",
            technician_id="10003",
            ledger_posted=True,
            reconciled=False,
        ),
    )
    repo.save(
        _complete_snapshot(
            period_id="b:1",
            technician_id="10010",
            ledger_posted=True,
            reconciled=False,
        ),
    )
    repo.save(
        replace(
            _complete_snapshot(period_id="c:1", technician_id="10020", status="pending_sales"),
            closed_at=datetime(2026, 6, 10, tzinfo=UTC),
        ),
    )
    repo.save(
        replace(
            _complete_snapshot(period_id="d:1", technician_id="10099", status="pending_sales"),
            closed_at=datetime(2026, 6, 20, tzinfo=UTC),
        ),
    )

    result = repo.list_reconciliation_preview_technician_ids()

    assert result == (
        TechnicianId("10003"),
        TechnicianId("10010"),
        TechnicianId("10020"),
        TechnicianId("10099"),
    )


def test_list_preview_candidates_includes_pending_after_any_moment() -> None:
    """edge: pending_sales без фильтра closed_at; в union вместе с posted."""
    repo = _repo()
    repo.save(
        _complete_snapshot(
            period_id="a:1",
            technician_id="10003",
            ledger_posted=True,
            reconciled=False,
        ),
    )
    repo.save(
        replace(
            _complete_snapshot(period_id="d:1", technician_id="10099", status="pending_sales"),
            closed_at=datetime(2026, 6, 20, tzinfo=UTC),
        ),
    )
    result = repo.list_reconciliation_preview_technician_ids()
    assert result == (TechnicianId("10003"), TechnicianId("10099"))


def test_list_reconciliation_preview_technician_ids_empty() -> None:
    repo = _repo()

    assert repo.list_reconciliation_preview_technician_ids() == ()


def test_snapshot_roundtrip_persists_party_names() -> None:
    snapshot = replace(
        _complete_snapshot(),
        location_name="Loc A",
        technician_name="Tech B",
    )

    document = snapshot_to_document(snapshot)
    loaded = snapshot_from_document(document)

    assert loaded.location_name == "Loc A"
    assert loaded.technician_name == "Tech B"
    assert isinstance(document["location_name"], str)
    assert isinstance(document["technician_name"], str)


def test_snapshot_from_document_missing_party_names_are_empty() -> None:
    document = snapshot_to_document(_complete_snapshot())
    document.pop("location_name", None)
    document.pop("technician_name", None)

    loaded = snapshot_from_document(document)

    assert loaded.location_name == ""
    assert loaded.technician_name == ""


def test_snapshot_from_document_null_party_names_are_empty() -> None:
    document = snapshot_to_document(_complete_snapshot())
    document["location_name"] = None
    document["technician_name"] = None

    loaded = snapshot_from_document(document)

    assert loaded.location_name == ""
    assert loaded.technician_name == ""


def test_snapshot_from_document_non_str_party_name_raises() -> None:
    document = snapshot_to_document(_complete_snapshot())
    document["location_name"] = 123

    with pytest.raises(ValueError, match="invalid shape"):
        snapshot_from_document(document)
