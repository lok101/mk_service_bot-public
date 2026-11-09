from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import IncidentSource, VisitStatus
from src.application.service_visits.ports import ServiceVisitStore

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class SweepResult:
    cleared_count: int = 0


@beartype
class SweepOpenOfflineExtras:
    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    @beartype
    def execute(self, *, now: datetime) -> SweepResult:
        open_offline = self._store.list_open_extras(incident_source=IncidentSource.OFFLINE)
        for visit in open_offline:
            self._store.upsert(
                replace(
                    visit,
                    status=VisitStatus.CLEARED,
                    closable=False,
                    updated_at=now,
                ),
            )
        cleared_count = len(open_offline)
        _LOGGER.info(
            "service_visit_offline_extra_sweep cleared_count=%s",
            cleared_count,
            extra={"cleared_count": cleared_count},
        )
        return SweepResult(cleared_count=cleared_count)
