from __future__ import annotations

import logging
from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions.ports import FormSubmissionStore
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.application.technician_warehouse.ports import (
    TechnicianWarehouseRepository,
    WarehouseLoadingBackfillSource,
)
from src.domain.form_submission import FrozenInventoryLine
from src.domain.ids import TechnicianId
from src.domain.quantities import packages_to_base_quantity

logger = logging.getLogger(__name__)

_SAMPLE_LIMIT = 20
_LOADING_PURPOSES = frozenset({"loading"})


@beartype
@dataclass(frozen=True, slots=True)
class BackfillWarehouseLoadingsReport:
    candidates: int
    would_fail_closed: int
    observed: int
    skipped_missing_snapshot: int
    skipped_wrong_purpose: int
    skipped_empty_lines: int
    skipped_already: int
    sample_event_ids: tuple[str, ...]
    sample_would_fail_closed_event_ids: tuple[str, ...]


class BackfillWarehouseLoadingsAborted(Exception):
    def __init__(self, *, technician_id: TechnicianId, event_id: str) -> None:
        self.technician_id = technician_id
        self.event_id = event_id
        super().__init__(
            f"warehouse already closed for technician_id={technician_id.value} event_id={event_id}"
        )


@beartype
def _has_observable_loading_lines(lines: tuple[FrozenInventoryLine, ...]) -> bool:
    for line in lines:
        pack_size = line.product_spec.pack_size
        if pack_size is None:
            continue
        quantity_base = packages_to_base_quantity(
            packages=line.quantity,
            pack_size=pack_size,
        )
        if quantity_base > 0:
            return True
    return False


@beartype
@dataclass(frozen=True, slots=True)
class BackfillTechnicianWarehouseLoadings:
    source: WarehouseLoadingBackfillSource
    form_submission_store: FormSubmissionStore
    observe_loading: ObserveTechnicianWarehouseLoading
    repository: TechnicianWarehouseRepository

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId | None,
        confirm: bool,
    ) -> BackfillWarehouseLoadingsReport:
        observed_ids = self.source.list_observed_source_event_ids(
            technician_id=technician_id,
        )
        submitted = self.source.list_loading_submitted(technician_id=technician_id)
        candidates = tuple(item for item in submitted if item.event_id not in observed_ids)
        sample_event_ids = tuple(item.event_id for item in candidates[:_SAMPLE_LIMIT])

        would_fail_closed = 0
        sample_closed: list[str] = []
        for item in candidates:
            if self.repository.get(item.technician_id).is_closed():
                would_fail_closed += 1
                if len(sample_closed) < _SAMPLE_LIMIT:
                    sample_closed.append(item.event_id)

        if not confirm:
            return BackfillWarehouseLoadingsReport(
                candidates=len(candidates),
                would_fail_closed=would_fail_closed,
                observed=0,
                skipped_missing_snapshot=0,
                skipped_wrong_purpose=0,
                skipped_empty_lines=0,
                skipped_already=0,
                sample_event_ids=sample_event_ids,
                sample_would_fail_closed_event_ids=tuple(sample_closed),
            )

        logger.info(
            "backfill_warehouse_loadings started candidates=%s technician_id=%s",
            len(candidates),
            None if technician_id is None else technician_id.value,
        )
        observed = 0
        skipped_missing_snapshot = 0
        skipped_wrong_purpose = 0
        skipped_empty_lines = 0
        skipped_already = 0

        for item in candidates:
            if self.repository.get(item.technician_id).is_closed():
                logger.error(
                    "backfill_warehouse_loadings aborted closed technician_id=%s event_id=%s",
                    item.technician_id.value,
                    item.event_id,
                )
                raise BackfillWarehouseLoadingsAborted(
                    technician_id=item.technician_id,
                    event_id=item.event_id,
                )

            snapshot = self.form_submission_store.get_by_event_id(item.event_id)
            if snapshot is None:
                skipped_missing_snapshot += 1
                logger.warning(
                    "backfill skip missing snapshot event_id=%s",
                    item.event_id,
                )
                continue
            if snapshot.purpose not in _LOADING_PURPOSES:
                skipped_wrong_purpose += 1
                logger.warning(
                    "backfill skip wrong purpose event_id=%s purpose=%s",
                    item.event_id,
                    snapshot.purpose,
                )
                continue
            if not _has_observable_loading_lines(snapshot.validated_lines):
                skipped_empty_lines += 1
                logger.info("backfill skip empty lines event_id=%s", item.event_id)
                continue

            result = self.observe_loading.execute(
                technician_id=item.technician_id,
                source_event_id=item.event_id,
                machine_id=item.machine_id,
                submitted_at=item.submitted_at,
                lines=snapshot.validated_lines,
            )
            if result is None:
                skipped_already += 1
                continue
            observed += 1

        report = BackfillWarehouseLoadingsReport(
            candidates=len(candidates),
            would_fail_closed=would_fail_closed,
            observed=observed,
            skipped_missing_snapshot=skipped_missing_snapshot,
            skipped_wrong_purpose=skipped_wrong_purpose,
            skipped_empty_lines=skipped_empty_lines,
            skipped_already=skipped_already,
            sample_event_ids=sample_event_ids,
            sample_would_fail_closed_event_ids=tuple(sample_closed),
        )
        logger.info(
            "backfill_warehouse_loadings completed observed=%s "
            "skipped_missing=%s skipped_wrong_purpose=%s "
            "skipped_empty=%s skipped_already=%s",
            observed,
            skipped_missing_snapshot,
            skipped_wrong_purpose,
            skipped_empty_lines,
            skipped_already,
        )
        return report
