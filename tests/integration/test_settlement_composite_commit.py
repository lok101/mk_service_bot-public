from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pymongo.database import Database

from src.application.technician_settlement.errors import TechnicianSettlementConcurrencyError
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.domain.ids import (
    AccountabilityId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement.aggregate import (
    CompleteReconciliationSession,
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import TechnicianReconciliationSessionCommitted
from src.infrastructure.mongodb.technician_settlement import (
    MongoTechnicianSettlementEventStore,
    MongoTechnicianSettlementRepository,
)

pytestmark = pytest.mark.integration

_TECH = TechnicianId("tech-composite")
_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)
_COLLECTION = "technician_settlement_events_composite"


def _seed_accountability(repository: MongoTechnicianSettlementRepository) -> None:
    aggregate = repository.get(_TECH)
    aggregate.record_period_accountability(
        RecordPeriodAccountability(
            accountability_id=AccountabilityId(f"{_TECH.value}:p1"),
            period_id="p1",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"coffee": Decimal("-1000")},
            closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        ),
    )
    repository.save(aggregate)


def _complete_command() -> CompleteReconciliationSession:
    return CompleteReconciliationSession(
        session_id=ReconciliationSessionId("sess-composite-1"),
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-1000")},
        residual_by_sku={},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )


def test_settlement_session_is_one_durable_event_and_duplicate_is_one_effect(
    mongo_database: Database,
) -> None:
    event_store = MongoTechnicianSettlementEventStore.from_collection(
        mongo_database[_COLLECTION],
    )
    repository = MongoTechnicianSettlementRepository(event_store=event_store)
    _seed_accountability(repository)

    executor = TechnicianSettlementExecutor(repository=repository)
    first = executor.execute(
        _TECH,
        lambda aggregate: aggregate.complete_reconciliation_session(_complete_command()),
    )
    second = executor.execute(
        _TECH,
        lambda aggregate: aggregate.complete_reconciliation_session(_complete_command()),
    )
    assert first.committed_event.event_id == second.committed_event.event_id

    raw = list(mongo_database[_COLLECTION].find({"aggregate_id": _TECH.value}))
    event_types = [document["event_type"] for document in raw]
    assert event_types.count("TechnicianReconciliationSessionCommitted") == 1
    assert "TechnicianReconciliationSessionCompleted" not in event_types
    assert "TechnicianLedgerClearedByReconciliation" not in event_types

    replayed = repository.get(_TECH)
    assert replayed.net_balance_by_sku()["coffee"] == Decimal("0")
    result = replayed.completion_result_for(ReconciliationSessionId("sess-composite-1"))
    assert result is not None
    assert isinstance(result.committed_event, TechnicianReconciliationSessionCommitted)


def test_two_stale_settlement_aggregates_have_one_winner_and_loser_reloads(
    mongo_database: Database,
) -> None:
    event_store = MongoTechnicianSettlementEventStore.from_collection(
        mongo_database[f"{_COLLECTION}_race"],
    )
    repository = MongoTechnicianSettlementRepository(event_store=event_store)
    _seed_accountability(repository)

    aggregate_a = repository.get(_TECH)
    aggregate_b = repository.get(_TECH)
    assert aggregate_a.loaded_version == 1
    assert aggregate_b.loaded_version == 1

    result_a = aggregate_a.complete_reconciliation_session(_complete_command())
    repository.save(aggregate_a)

    result_b = aggregate_b.complete_reconciliation_session(
        CompleteReconciliationSession(
            session_id=ReconciliationSessionId("sess-composite-stale"),
            mode="inventory_delta",
            anchor_at=_ANCHOR,
            period_ids=("p1",),
            deferred_period_ids=(),
            warehouse_inventory_id="warehouse-inv-2",
            warehouse_inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=(),
            ledger_balance_before={"coffee": Decimal("-1000")},
            residual_by_sku={},
            finalized_at=datetime(2026, 5, 25, 2, tzinfo=UTC),
            executed_at=datetime(2026, 5, 25, 2, tzinfo=UTC),
        ),
    )
    stale_event_id = result_b.committed_event.event_id.value
    with pytest.raises(TechnicianSettlementConcurrencyError):
        repository.save(aggregate_b)

    observed_versions: list[int] = []

    def command_fn(aggregate: TechnicianSettlement) -> object:
        observed_versions.append(aggregate.loaded_version)
        return aggregate.record_period_accountability(
            RecordPeriodAccountability(
                accountability_id=AccountabilityId(f"{_TECH.value}:p-reload"),
                period_id="p-reload",
                machine_id=MachineId("vm-01"),
                delta_by_sku={"coffee": Decimal("-1")},
                closed_at=datetime(2026, 5, 26, tzinfo=UTC),
            ),
        )

    executor = TechnicianSettlementExecutor(repository=repository, max_save_retries=5)
    executor.execute(_TECH, command_fn)
    assert observed_versions == [2]

    durable = event_store.get_events_for_technician(_TECH)
    assert isinstance(durable[1], TechnicianReconciliationSessionCommitted)
    assert durable[1].event_id == result_a.committed_event.event_id
    assert all(event.event_id.value != stale_event_id for event in durable)
