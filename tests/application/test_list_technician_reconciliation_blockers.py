from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.technician_settlement.list_technician_reconciliation_blockers import (
    ListTechnicianReconciliationBlockers,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_operations import (
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    SubmitLoading,
)
from src.domain.models import RevisionSource, VendingMachine
from src.infrastructure.testing.settlement_fakes import InMemoryPeriodReconciliationRepository

_TECH = TechnicianId("10003")
_VM_A = MachineId("vm-a")
_VM_B = MachineId("vm-b")
_OPENED_EARLY = datetime(2026, 6, 1, 10, 15, tzinfo=UTC)
_OPENED_LATE = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
_CHECKED_AT = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
_MSK = ZoneInfo("Europe/Moscow")


class _Machines:
    def __init__(self, machines: list[VendingMachine]) -> None:
        self._machines = {machine.id: machine for machine in machines}

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return self._machines.get(machine_id)

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        mapping = {
            _VM_A: "Иванов И.",
            _VM_B: "Петров П.",
        }
        return mapping.get(machine_id)

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return "Иванов И." if technician_id == _TECH else None

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return list(self._machines.values())

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


class _MachineOps:
    def get(self, machine_id: MachineId) -> MachineOperations:
        return MachineOperations.empty(machine_id)

    def save(self, aggregate: MachineOperations) -> None:
        pass


def _pending_snapshot(
    *,
    machine_id: MachineId,
    opened_at: datetime,
    period_id: str,
    location_name: str = "",
    technician_name: str = "",
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=machine_id,
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=opened_at,
        closed_at=datetime(2026, 6, 8, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
        location_name=location_name,
        technician_name=technician_name,
    )


def _aggregate_with_revision(
    machine_id: MachineId,
    *,
    technician_id: TechnicianId = _TECH,
    completed_at: datetime,
    form_token: str = "token-rev",
) -> MachineOperations:
    aggregate = MachineOperations.empty(machine_id, revision_interval_min_days=7)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=technician_id,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token=f"load-before-{form_token}",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=technician_id,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token=form_token,
        ),
    )
    assert result is not None
    return aggregate


class _MachineOpsFromMap:
    def __init__(self, aggregates: dict[MachineId, MachineOperations]) -> None:
        self._aggregates = aggregates

    def get(self, machine_id: MachineId) -> MachineOperations:
        return self._aggregates.get(machine_id, MachineOperations.empty(machine_id))

    def save(self, aggregate: MachineOperations) -> None:
        pass


def test_lists_pending_sales_for_technician_sorted_by_opened_at_then_name() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        _pending_snapshot(
            machine_id=_VM_B,
            opened_at=_OPENED_LATE,
            period_id="p-late",
            location_name="Локация Б",
            technician_name="Иванов И.",
        ),
    )
    repo.save(
        _pending_snapshot(
            machine_id=_VM_A,
            opened_at=_OPENED_EARLY,
            period_id="p-early",
            location_name="Локация А",
            technician_name="Иванов И.",
        ),
    )
    repo.save(
        replace(
            _pending_snapshot(
                machine_id=_VM_A,
                opened_at=_OPENED_EARLY,
                period_id="p-other-tech",
                location_name="Локация А",
                technician_name="Other",
            ),
            responsible_technician_id=TechnicianId("99999"),
        ),
    )
    machines = _Machines(
        [
            VendingMachine(id=_VM_A, name="Live А"),
            VendingMachine(id=_VM_B, name="Live Б"),
        ],
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=_MachineOps(),
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert result.technician_name == "Иванов И."
    assert len(result.pending_sales) == 2
    assert result.pending_sales[0].machine_name == "Локация А"
    assert result.pending_sales[0].opened_at == "01.06.2026 13:15:00"
    assert result.pending_sales[0].assigned_technician == "Иванов И."
    assert result.pending_sales[0].status == "pending_sales"
    assert result.pending_sales[1].machine_name == "Локация Б"
    assert result.operational_open == ()


def test_pending_sales_rows_use_snapshot_party_names() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        _pending_snapshot(
            machine_id=_VM_A,
            opened_at=_OPENED_EARLY,
            period_id="p-frozen",
            location_name="Frozen Loc",
            technician_name="Frozen Tech",
        ),
    )
    machines = _Machines([VendingMachine(id=_VM_A, name="Live Loc")])
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=_MachineOps(),
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.pending_sales) == 1
    row = result.pending_sales[0]
    assert row.machine_name == "Frozen Loc"
    assert row.assigned_technician == "Frozen Tech"
    assert row.status == "pending_sales"


def test_operational_open_rows_still_use_live_display_names() -> None:
    opened_at = datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    machines = _Machines([VendingMachine(id=_VM_A, name="Live Open Loc")])
    machine_ops = _MachineOpsFromMap(
        {_VM_A: _aggregate_with_revision(_VM_A, completed_at=opened_at)},
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.operational_open) == 1
    row = result.operational_open[0]
    assert row.machine_name == "Live Open Loc"
    assert row.assigned_technician == "Иванов И."
    assert row.status == "operational_open"


def test_lists_operational_open_when_technician_is_responsible() -> None:
    opened_at = datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    machines = _Machines([VendingMachine(id=_VM_A, name="Локация В")])
    machine_ops = _MachineOpsFromMap(
        {_VM_A: _aggregate_with_revision(_VM_A, completed_at=opened_at)},
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.operational_open) == 1
    row = result.operational_open[0]
    assert row.machine_name == "Локация В"
    assert row.opened_at == "10.06.2026 17:00:00"
    assert row.assigned_technician == "Иванов И."
    assert row.status == "operational_open"


def test_lists_expired_unclosed_when_period_expired_without_snapshot() -> None:
    opened_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    checked_at = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    aggregate = _aggregate_with_revision(
        _VM_A,
        completed_at=opened_at,
        form_token="token-expired",
    )
    machines = _Machines([VendingMachine(id=_VM_A, name="Локация Г")])
    machine_ops = _MachineOpsFromMap({_VM_A: aggregate})
    repo = InMemoryPeriodReconciliationRepository()
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=checked_at)

    assert len(result.operational_open) == 1
    assert result.operational_open[0].status == "expired_unclosed"
    assert result.operational_open[0].machine_name == "Локация Г"


def test_skips_operational_open_when_machine_already_in_pending_sales() -> None:
    opened_at = datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_pending_snapshot(machine_id=_VM_A, opened_at=opened_at, period_id="p-dup"))
    machines = _Machines([VendingMachine(id=_VM_A, name="Локация А")])
    machine_ops = _MachineOpsFromMap(
        {_VM_A: _aggregate_with_revision(_VM_A, completed_at=opened_at)},
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.pending_sales) == 1
    assert result.operational_open == ()


class _MachinesWithoutAssignment(_Machines):
    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return None


def test_assigned_technician_fallback_when_missing_in_sheets() -> None:
    opened_at = datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    machines = _MachinesWithoutAssignment([VendingMachine(id=_VM_A, name="Локация X")])
    machine_ops = _MachineOpsFromMap(
        {_VM_A: _aggregate_with_revision(_VM_A, completed_at=opened_at)},
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert result.operational_open[0].assigned_technician == "не найден в таблице"


def test_pending_sales_empty_party_names_when_snapshot_fields_empty() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        _pending_snapshot(
            machine_id=_VM_A,
            opened_at=_OPENED_EARLY,
            period_id="p-no-name",
        ),
    )
    machines = _Machines([VendingMachine(id=_VM_A, name="Live Loc")])
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=_MachineOps(),
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.pending_sales) == 1
    assert result.pending_sales[0].machine_name == ""
    assert result.pending_sales[0].assigned_technician == ""


def test_expired_unclosed_skipped_when_snapshot_exists_for_opening_revision() -> None:
    opened_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    checked_at = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    aggregate = _aggregate_with_revision(
        _VM_A,
        completed_at=opened_at,
        form_token="token-has-snapshot",
    )
    revision_id = aggregate.last_revision_id()
    assert revision_id is not None
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="rev-open:rev-close",
            machine_id=_VM_A,
            responsible_technician_id=_TECH,
            opening_revision_id=revision_id,
            closing_revision_id=RevisionId("rev-close"),
            opened_at=opened_at,
            closed_at=datetime(2026, 6, 8, tzinfo=UTC),
            lines=(),
            sales_lines=(),
            load_count=0,
            status="complete",
        ),
    )
    machines = _Machines([VendingMachine(id=_VM_A, name="Локация Г")])
    machine_ops = _MachineOpsFromMap({_VM_A: aggregate})
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=repo,
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=checked_at)

    assert result.operational_open == ()


def test_operational_open_sorted_by_opened_at_then_machine_name() -> None:
    opened_early = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
    opened_late = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)
    machines = _Machines(
        [
            VendingMachine(id=_VM_A, name="Локация А"),
            VendingMachine(id=_VM_B, name="Локация Б"),
        ],
    )
    machine_ops = _MachineOpsFromMap(
        {
            _VM_A: _aggregate_with_revision(
                _VM_A,
                completed_at=opened_late,
                form_token="token-late",
            ),
            _VM_B: _aggregate_with_revision(
                _VM_B,
                completed_at=opened_early,
                form_token="token-early",
            ),
        },
    )
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        machines=machines,
        machine_operations=machine_ops,
        audit_timezone=_MSK,
    )

    result = use_case.execute(_TECH, checked_at=_CHECKED_AT)

    assert len(result.operational_open) == 2
    assert result.operational_open[0].machine_name == "Локация Б"
    assert result.operational_open[0].status == "operational_open"
    assert result.operational_open[1].machine_name == "Локация А"


def test_empty_sections_when_no_blockers_and_unknown_technician_name() -> None:
    machines = _Machines([])
    use_case = ListTechnicianReconciliationBlockers(
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        machines=machines,
        machine_operations=_MachineOps(),
        audit_timezone=_MSK,
    )

    result = use_case.execute(TechnicianId("unknown"), checked_at=_CHECKED_AT)

    assert result.technician_name == ""
    assert result.pending_sales == ()
    assert result.operational_open == ()
