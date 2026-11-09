from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from scripts.settlement_admin import main
from scripts.settlement_admin_lib import main as settlement_admin_main

from src.application.technician_settlement.preview_all_reconciliations import (
    PreviewAllTechniciansResult,
    TechnicianPreviewOutcome,
)
from src.application.technician_settlement.preview_reconciliation import ReconciliationPreview
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine

_ANCHOR = datetime(2026, 6, 15, 14, 30, tzinfo=UTC)
_MSK = ZoneInfo("Europe/Moscow")


class _Machines:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return None

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return None

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return f"Tech {technician_id.value}"

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


def _minimal_preview(technician_id: str) -> ReconciliationPreview:
    return ReconciliationPreview(
        technician_id=TechnicianId(technician_id),
        anchor_at=_ANCHOR,
        scope=(),
        deferred=(),
        ledger_balance_session={},
        warehouse_inventory_id="inv-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(),
        blockers=(),
        can_finalize=True,
        residual_by_sku={},
    )


@dataclass(frozen=True, slots=True)
class _FakePreviewAll:
    result: PreviewAllTechniciansResult
    machines: _Machines = _Machines()
    audit_timezone: ZoneInfo = _MSK

    def execute(self) -> PreviewAllTechniciansResult:
        return self.result


@dataclass(frozen=True, slots=True)
class _PreviewBatchDeps:
    preview_all: _FakePreviewAll
    preview: None = None
    finalize: None = None
    close_warehouse: None = None
    preview_exit: None = None
    finalize_exit: None = None
    draft_store: None = None
    list_status: None = None
    list_blockers: None = None
    audit_timezone: ZoneInfo = _MSK


def test_batch_preview_empty_candidates_prints_none_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deps = _PreviewBatchDeps(
        preview_all=_FakePreviewAll(
            result=PreviewAllTechniciansResult(outcomes=()),
        ),
    )
    monkeypatch.setattr(settlement_admin_main, "build_deps", lambda: deps)

    exit_code = main(
        ["reconcile", "preview"],
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "technicians: (none)"


def test_batch_preview_all_ok_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _PreviewBatchDeps(
        preview_all=_FakePreviewAll(
            result=PreviewAllTechniciansResult(
                outcomes=(
                    TechnicianPreviewOutcome(
                        technician_id=TechnicianId("10003"),
                        technician_name="Tech 10003",
                        status="ok",
                        reason="",
                        preview=_minimal_preview("10003"),
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(settlement_admin_main, "build_deps", lambda: deps)

    exit_code = main(["reconcile", "preview"])

    assert exit_code == 0


def test_batch_preview_with_blocked_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _PreviewBatchDeps(
        preview_all=_FakePreviewAll(
            result=PreviewAllTechniciansResult(
                outcomes=(
                    TechnicianPreviewOutcome(
                        technician_id=TechnicianId("10003"),
                        technician_name="Tech 10003",
                        status="ok",
                        reason="",
                        preview=_minimal_preview("10003"),
                    ),
                    TechnicianPreviewOutcome(
                        technician_id=TechnicianId("10010"),
                        technician_name="Tech 10010",
                        status="blocked",
                        reason="pending periods inside reconciliation window",
                        preview=None,
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(settlement_admin_main, "build_deps", lambda: deps)

    exit_code = main(["reconcile", "preview"])

    assert exit_code == 1
