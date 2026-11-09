from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement.aggregate import (
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)
from src.infrastructure.mongodb.technician_settlement import (
    MongoTechnicianSettlementEventStore,
    MongoTechnicianSettlementRepository,
)
from src.infrastructure.mongodb.technician_settlement_serialization import (
    settlement_event_from_document,
    settlement_event_to_document,
)

_TECH_ID = TechnicianId("tech-a")
_CLOSED_AT = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)


def test_append_event_and_rehydrate_aggregate() -> None:
    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    repository = MongoTechnicianSettlementRepository(event_store=event_store)

    aggregate = TechnicianSettlement.empty(_TECH_ID)
    aggregate.record_period_accountability(
        RecordPeriodAccountability(
            accountability_id=AccountabilityId("tech-a:p1"),
            period_id="p1",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"coffee-1": Decimal("-1")},
            closed_at=_CLOSED_AT,
        ),
    )
    repository.save(aggregate)

    rehydrated = repository.get(_TECH_ID)
    assert rehydrated.net_balance_by_sku() == {"coffee-1": Decimal("-1")}


def test_append_is_idempotent_by_event_id() -> None:
    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    event = PeriodAccountabilityRecorded(
        event_id=EventId("evt-1"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=_TECH_ID,
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-2")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    event_store.append(
        event,
        expected_version=0,
    )
    event_store.append(
        event,
        expected_version=1,
    )

    events = event_store.get_events_for_technician(_TECH_ID)
    assert len(events) == 1


def test_accountability_round_trip() -> None:
    event = PeriodAccountabilityRecorded(
        event_id=EventId("event-1"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=TechnicianId("tech-a"),
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-2")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    document = settlement_event_to_document(event, aggregate_version=1)
    restored = settlement_event_from_document(document)
    assert restored == event


def test_session_completed_round_trip() -> None:
    event = TechnicianReconciliationSessionCompleted(
        event_id=EventId("event-2"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        mode="inventory_delta",
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
        period_ids=("p1",),
        deferred_period_ids=("p2",),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=datetime(2026, 5, 25, tzinfo=UTC),
        warehouse_delta_by_sku={"coffee": Decimal("2")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-2")},
        residual_by_sku={"coffee": Decimal("0")},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    assert (
        settlement_event_from_document(
            settlement_event_to_document(event, aggregate_version=2),
        )
        == event
    )


def test_ledger_cleared_round_trip() -> None:
    event = TechnicianLedgerClearedByReconciliation(
        event_id=EventId("event-3"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        period_ids=("p1",),
        cleared_by_sku={"coffee": Decimal("-2")},
        residual_by_sku={"coffee": Decimal("0")},
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    assert (
        settlement_event_from_document(
            settlement_event_to_document(event, aggregate_version=3),
        )
        == event
    )


def test_session_committed_round_trip_preserves_completion_and_clear_fields() -> None:
    event = TechnicianReconciliationSessionCommitted(
        event_id=EventId("event-committed"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        mode="inventory_delta",
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
        period_ids=("p1",),
        deferred_period_ids=("p2",),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=datetime(2026, 5, 25, tzinfo=UTC),
        warehouse_delta_by_sku={"coffee": Decimal("2")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-2")},
        cleared_by_sku={"coffee": Decimal("-2")},
        residual_by_sku={"coffee": Decimal("0")},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    assert (
        settlement_event_from_document(
            settlement_event_to_document(event, aggregate_version=4),
        )
        == event
    )


def test_legacy_completed_round_trip_remains_supported() -> None:
    test_session_completed_round_trip()


def test_legacy_cleared_round_trip_remains_supported() -> None:
    test_ledger_cleared_round_trip()


def test_unknown_settlement_event_type_fails_closed() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unknown settlement event_type"):
        settlement_event_from_document(
            {
                "event_id": "evt-x",
                "event_type": "UnknownSettlementEvent",
                "aggregate_id": "tech-a",
                "aggregate_type": "TechnicianSettlement",
                "aggregate_version": 1,
                "occurred_at": datetime(2026, 5, 25, tzinfo=UTC),
                "payload": {},
            },
        )


def test_settlement_repository_rehydrates_loaded_version() -> None:
    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    repository = MongoTechnicianSettlementRepository(event_store=event_store)
    aggregate = TechnicianSettlement.empty(_TECH_ID)
    aggregate.record_period_accountability(
        RecordPeriodAccountability(
            accountability_id=AccountabilityId("tech-a:p1"),
            period_id="p1",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"coffee-1": Decimal("-1")},
            closed_at=_CLOSED_AT,
        ),
    )
    repository.save(aggregate)
    rehydrated = repository.get(_TECH_ID)
    assert rehydrated.loaded_version == 1


def test_settlement_store_writes_expected_version_plus_one() -> None:
    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    event = PeriodAccountabilityRecorded(
        event_id=EventId("evt-v1"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=_TECH_ID,
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-2")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    event_store.append(event, expected_version=0)
    document = collection.find_one({"event_id": "evt-v1"})
    assert document is not None
    assert document["aggregate_version"] == 1


def test_settlement_store_rejects_occupied_version_for_distinct_event() -> None:
    import pytest

    from src.infrastructure.mongodb.errors import EventStoreConcurrencyError

    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    first = PeriodAccountabilityRecorded(
        event_id=EventId("evt-first"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=_TECH_ID,
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-1")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    second = PeriodAccountabilityRecorded(
        event_id=EventId("evt-second"),
        accountability_id=AccountabilityId("tech-a:p2"),
        technician_id=_TECH_ID,
        period_id="p2",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-1")},
        closed_at=datetime(2026, 5, 2, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 2, 1, tzinfo=UTC),
    )
    event_store.append(first, expected_version=0)
    with pytest.raises(EventStoreConcurrencyError):
        event_store.append(second, expected_version=0)


def test_settlement_store_same_event_id_is_idempotent() -> None:
    collection = mongomock.MongoClient().db.technician_settlement_events
    event_store = MongoTechnicianSettlementEventStore.from_collection(collection)
    event = PeriodAccountabilityRecorded(
        event_id=EventId("evt-same"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=_TECH_ID,
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-2")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    event_store.append(event, expected_version=0)
    event_store.append(event, expected_version=0)
    assert len(event_store.get_events_for_technician(_TECH_ID)) == 1
