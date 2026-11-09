from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from scripts.settlement_admin import main
from scripts.settlement_admin_lib import main as settlement_admin_main

from src.application.technician_settlement.list_technician_reconciliation_blockers import (
    ListTechnicianReconciliationBlockers,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.models import VendingMachine
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore
from src.infrastructure.testing.settlement_fakes import InMemoryPeriodReconciliationRepository

_TECH = TechnicianId("10003")
_VM = MachineId("vm-cli")
_MSK = ZoneInfo("Europe/Moscow")


class _Machines:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=_VM, name="Локация А") if machine_id == _VM else None

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return "Иванов И." if machine_id == _VM else None

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return "Иванов И." if technician_id == _TECH else None

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return [VendingMachine(id=_VM, name="Локация А")]

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


@dataclass(frozen=True, slots=True)
class _ListBlockersDeps:
    list_blockers: ListTechnicianReconciliationBlockers
    preview: None = None
    preview_all: None = None
    finalize: None = None
    close_warehouse: None = None
    preview_exit: None = None
    finalize_exit: None = None
    draft_store: None = None
    list_status: None = None
    audit_timezone: ZoneInfo = _MSK


def _list_blockers_cli_deps() -> _ListBlockersDeps:
    repo = InMemoryPeriodReconciliationRepository()
    opened_at = datetime(2026, 6, 1, 10, 15, tzinfo=UTC)
    repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="p-cli",
            machine_id=_VM,
            responsible_technician_id=_TECH,
            opening_revision_id=RevisionId("open-p-cli"),
            closing_revision_id=RevisionId("close-p-cli"),
            opened_at=opened_at,
            closed_at=datetime(2026, 6, 8, tzinfo=UTC),
            lines=(),
            sales_lines=(),
            load_count=0,
            status="pending_sales",
            location_name="Локация А",
            technician_name="Иванов И.",
        ),
    )
    return _ListBlockersDeps(
        list_blockers=ListTechnicianReconciliationBlockers(
            reconciliation_repo=repo,
            machines=_Machines(),
            machine_operations=EventSourcedMachineOperationsRepository(
                event_store=InMemoryEventStore(),
            ),
            audit_timezone=_MSK,
        ),
    )


def test_list_blockers_prints_report_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(settlement_admin_main, "build_deps", _list_blockers_cli_deps)

    exit_code = main(["list-blockers", "--technician-id", "10003"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "technician_id=10003" in output
    assert "technician_name=Иванов И." in output
    assert "pending_sales_count=1" in output
    assert "operational_open_count=0" in output
    assert "[pending_sales]" in output
    header_line = output.split("[pending_sales]\n", 1)[1].splitlines()[0]
    assert header_line.startswith("machine_name")
    assert "opened_at" in header_line
    assert "assigned_technician" in header_line
    assert "status" in header_line
    assert "Локация А" in output
    assert "[operational_open]" in output
    assert "(none)" in output
