from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_settlement.errors import TechnicianSettlementConcurrencyError
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.domain.ids import AccountabilityId, MachineId, TechnicianId
from src.domain.technician_settlement.aggregate import (
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)


def _sample_command() -> RecordPeriodAccountability:
    return RecordPeriodAccountability(
        accountability_id=AccountabilityId("rev-0:rev-1"),
        period_id="rev-0:rev-1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee-1": Decimal("-1")},
        closed_at=_CLOSED,
    )


@dataclass(slots=True)
class FailingOnceTechnicianSettlementRepository(TechnicianSettlementRepository):
    inner: InMemoryTechnicianSettlementRepository
    error: TechnicianSettlementConcurrencyError
    _failed: bool = False

    @property
    def event_store(self):  # type: ignore[no-untyped-def]
        return self.inner.event_store

    def get(self, technician_id: TechnicianId) -> TechnicianSettlement:
        return self.inner.get(technician_id)

    def save(self, aggregate: TechnicianSettlement) -> None:
        if not self._failed:
            self._failed = True
            raise self.error
        self.inner.save(aggregate)


@dataclass(slots=True)
class FailingAlwaysTechnicianSettlementRepository(TechnicianSettlementRepository):
    error: TechnicianSettlementConcurrencyError

    @property
    def event_store(self):  # type: ignore[no-untyped-def]
        from src.infrastructure.testing.settlement_fakes import (
            InMemoryTechnicianSettlementEventStore,
        )

        return InMemoryTechnicianSettlementEventStore()

    def get(self, technician_id: TechnicianId) -> TechnicianSettlement:
        return TechnicianSettlement.empty(technician_id)

    def save(self, aggregate: TechnicianSettlement) -> None:
        raise self.error


def test_executor_retries_on_concurrency_error() -> None:
    inner = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    repo = FailingOnceTechnicianSettlementRepository(
        inner=inner,
        error=TechnicianSettlementConcurrencyError(technician_id=TechnicianId("tech-a")),
    )
    executor = TechnicianSettlementExecutor(repository=repo)
    calls = {"n": 0}

    def _run(aggregate: TechnicianSettlement) -> object:
        calls["n"] += 1
        return aggregate.record_period_accountability(_sample_command())

    executor.execute(TechnicianId("tech-a"), _run)
    assert calls["n"] == 2


def test_executor_raises_after_max_retries() -> None:
    repo = FailingAlwaysTechnicianSettlementRepository(
        error=TechnicianSettlementConcurrencyError(technician_id=TechnicianId("tech-a")),
    )
    executor = TechnicianSettlementExecutor(
        repository=repo,
        max_save_retries=3,
    )

    with pytest.raises(TechnicianSettlementConcurrencyError):
        executor.execute(
            TechnicianId("tech-a"),
            lambda aggregate: aggregate.record_period_accountability(_sample_command()),
        )


def test_executor_skips_save_when_command_is_idempotent() -> None:
    settlement_repo = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    executor = TechnicianSettlementExecutor(repository=settlement_repo)
    tech_id = TechnicianId("tech-a")
    command = _sample_command()

    def _run(aggregate: TechnicianSettlement) -> object:
        return aggregate.record_period_accountability(command)

    executor.execute(tech_id, _run)
    assert len(settlement_repo.events) == 1

    executor.execute(tech_id, _run)

    assert len(settlement_repo.events) == 1


def test_settlement_executor_reloads_after_conflict() -> None:
    inner = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    repo = FailingOnceTechnicianSettlementRepository(
        inner=inner,
        error=TechnicianSettlementConcurrencyError(technician_id=TechnicianId("tech-a")),
    )
    executor = TechnicianSettlementExecutor(repository=repo)
    observed_versions: list[int] = []

    def _run(aggregate: TechnicianSettlement) -> object:
        observed_versions.append(aggregate.loaded_version)
        return aggregate.record_period_accountability(_sample_command())

    executor.execute(TechnicianId("tech-a"), _run)
    assert observed_versions == [0, 0]
    assert len(inner.events) == 1
