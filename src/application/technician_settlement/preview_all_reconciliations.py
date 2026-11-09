from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import VendingMachineRepository
from src.application.shared.display_names import technician_display_name
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
    ReconciliationBlocked,
    ReconciliationPreview,
)
from src.domain.ids import TechnicianId

PreviewStatus = str  # "ok" | "blocked" | "skipped"

_SKIPPED_REASON = "nothing to reconcile in window"


@beartype
def _preview_status_for_blocked(error: ReconciliationBlocked) -> str:
    message = str(error)
    if message == _SKIPPED_REASON:
        return "skipped"
    return "blocked"


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianPreviewOutcome:
    technician_id: TechnicianId
    technician_name: str
    status: PreviewStatus
    reason: str
    preview: ReconciliationPreview | None


@beartype
@dataclass(frozen=True, slots=True)
class PreviewAllTechniciansResult:
    outcomes: tuple[TechnicianPreviewOutcome, ...]

    @property
    def processed(self) -> int:
        return len(self.outcomes)

    @property
    def succeeded(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "ok")

    @property
    def blocked(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "blocked")

    @property
    def skipped(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "skipped")


@beartype
@dataclass(frozen=True, slots=True)
class PreviewAllTechniciansReconciliation:
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    preview: PreviewTechnicianReconciliation
    machines: VendingMachineRepository

    @beartype
    def execute(self) -> PreviewAllTechniciansResult:
        technician_ids = self.reconciliation_repo.list_reconciliation_preview_technician_ids()
        outcomes: list[TechnicianPreviewOutcome] = []
        for technician_id in technician_ids:
            technician_name = technician_display_name(
                self.machines,
                technician_id,
                fallback="",
            )
            try:
                preview = self.preview.build_preview(technician_id=technician_id)
            except ReconciliationBlocked as error:
                status = _preview_status_for_blocked(error)
                outcomes.append(
                    TechnicianPreviewOutcome(
                        technician_id=technician_id,
                        technician_name=technician_name,
                        status=status,
                        reason=str(error),
                        preview=None,
                    ),
                )
                continue
            if not preview.can_finalize:
                outcomes.append(
                    TechnicianPreviewOutcome(
                        technician_id=technician_id,
                        technician_name=technician_name,
                        status="blocked",
                        reason="; ".join(preview.blockers),
                        preview=preview,
                    ),
                )
                continue
            outcomes.append(
                TechnicianPreviewOutcome(
                    technician_id=technician_id,
                    technician_name=technician_name,
                    status="ok",
                    reason="",
                    preview=preview,
                ),
            )
        return PreviewAllTechniciansResult(outcomes=tuple(outcomes))
