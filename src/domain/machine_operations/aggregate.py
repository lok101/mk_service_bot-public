from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import (
    DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    calendar_anchor,
    operational_day,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.commands import (
    CompleteMaintenance,
    CompleteRevision,
    SubmitLoading,
    SubmitLoadingPhotos,
)
from src.domain.machine_operations.events import (
    DomainEvent,
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.machine_operations.snapshot import RevisionSnapshot
from src.domain.models import PrefilledFormLink
from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON,
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_REQUIRE_LOADING_REASON,
    MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    REVISION_NOT_ALLOWED_REASON,
    LoadingNotAllowed,
    LoadingPhotosAlreadySubmittedToday,
    LoadingPhotosInsufficientCount,
    LoadingPhotosNotAllowed,
    MaintenanceAlreadyCompletedToday,
    MaintenanceNotAllowed,
    ResponsibilityPhase,
    RevisionDueStatus,
    RevisionNotAllowed,
    ServiceCapabilities,
)
from src.domain.revision_due_policy import (
    compute_responsibility_expires_at,
    compute_revision_due_status,
)


@beartype
@dataclass(slots=True)
class MachineOperations:
    machine_id: MachineId
    revision_interval_min_days: int | None = field(default=None, repr=False)
    revision_interval_max_days: int | None = field(default=None, repr=False)
    service_calendar_timezone: ZoneInfo = field(
        default=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        repr=False,
    )
    service_day_end_hour: int = field(default=6, repr=False)
    # Граница, открывающая текущий период ответственности: техник этой ревизии
    # несёт ответственность за интервал до следующей ревизии.
    _last_revision: RevisionSnapshot | None = field(default=None, repr=False)
    _revision_by_token: dict[str, RevisionCompleted] = field(
        default_factory=dict,
        repr=False,
    )
    _loading_by_token: dict[str, LoadingSubmitted] = field(
        default_factory=dict,
        repr=False,
    )
    _photos_by_batch_id: dict[str, PhotosSubmitted] = field(
        default_factory=dict,
        repr=False,
    )
    _last_loading_submitted_at: datetime | None = field(default=None, repr=False)
    _maintenance_completed_days: set[date] = field(default_factory=set, repr=False)
    _photos_submitted_days: set[date] = field(default_factory=set, repr=False)
    _last_maintenance_completed_at: datetime | None = field(default=None, repr=False)
    _pending_events: list[DomainEvent] = field(default_factory=list, repr=False)
    _loaded_version: int = field(default=0, repr=False)

    @property
    @beartype
    def loaded_version(self) -> int:
        return self._loaded_version

    @classmethod
    @beartype
    def _resolve_interval_settings(
        cls,
        *,
        responsibility_period_days: int | None = None,
        revision_interval_min_days: int | None = None,
        revision_interval_max_days: int | None = None,
    ) -> tuple[int | None, int | None]:
        min_days = revision_interval_min_days
        max_days = revision_interval_max_days
        if responsibility_period_days is not None:
            if min_days is None:
                min_days = responsibility_period_days
            if max_days is None:
                max_days = responsibility_period_days
        return min_days, max_days

    @classmethod
    @beartype
    def empty(
        cls,
        machine_id: MachineId,
        *,
        responsibility_period_days: int | None = None,
        revision_interval_min_days: int | None = None,
        revision_interval_max_days: int | None = None,
        service_calendar_timezone: ZoneInfo = DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        service_day_end_hour: int = 6,
    ) -> MachineOperations:
        min_days, max_days = cls._resolve_interval_settings(
            responsibility_period_days=responsibility_period_days,
            revision_interval_min_days=revision_interval_min_days,
            revision_interval_max_days=revision_interval_max_days,
        )
        return cls(
            machine_id=machine_id,
            revision_interval_min_days=min_days,
            revision_interval_max_days=max_days,
            service_calendar_timezone=service_calendar_timezone,
            service_day_end_hour=service_day_end_hour,
        )

    @classmethod
    @beartype
    def rehydrate(
        cls,
        machine_id: MachineId,
        events: list[DomainEvent],
        *,
        responsibility_period_days: int | None = None,
        revision_interval_min_days: int | None = None,
        revision_interval_max_days: int | None = None,
        service_calendar_timezone: ZoneInfo = DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        service_day_end_hour: int = 6,
        loaded_version: int | None = None,
    ) -> MachineOperations:
        min_days, max_days = cls._resolve_interval_settings(
            responsibility_period_days=responsibility_period_days,
            revision_interval_min_days=revision_interval_min_days,
            revision_interval_max_days=revision_interval_max_days,
        )
        aggregate = cls(
            machine_id=machine_id,
            revision_interval_min_days=min_days,
            revision_interval_max_days=max_days,
            service_calendar_timezone=service_calendar_timezone,
            service_day_end_hour=service_day_end_hour,
        )
        for event in events:
            aggregate._apply(event)
        aggregate._loaded_version = len(events) if loaded_version is None else loaded_version
        return aggregate

    @beartype
    def responsibility_phase(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> ResponsibilityPhase:
        return self._responsibility_phase(technician_id, checked_at=checked_at)

    @beartype
    def last_revision_opened_at(self) -> datetime | None:
        if self._last_revision is None:
            return None
        return self._last_revision.completed_at

    @beartype
    def last_revision_id(self) -> RevisionId | None:
        if self._last_revision is None:
            return None
        return self._last_revision.revision_id

    @beartype
    def last_revision_opened_by(self) -> TechnicianId | None:
        if self._last_revision is None:
            return None
        return self._last_revision.technician_id

    @beartype
    def get_service_capabilities(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
        revision_form_link: PrefilledFormLink | None = None,
        skip_responsibility_check: bool = False,
        allow_additional_maintenance: bool = False,
        allow_missing_revision_form: bool = False,
    ) -> ServiceCapabilities:
        phase = self._responsibility_phase(technician_id, checked_at=checked_at)
        if skip_responsibility_check and phase == "awaiting_handover":
            if revision_form_link is None and not allow_missing_revision_form:
                raise ValueError(
                    "revision_form_link is required for awaiting_handover phase",
                )
            reference_at = checked_at or datetime.now(tz=UTC)
            maintenance_completed_today = self._maintenance_completed_today(
                checked_at=reference_at,
            )
            if allow_missing_revision_form:
                # Micromarket/snack bypass: coffee loading form is not required.
                return ServiceCapabilities(
                    technician_id=technician_id,
                    machine_id=self.machine_id,
                    responsibility_phase="responsible",
                    can_complete_revision=False,
                    can_submit_loading=False,
                    can_submit_loading_photos=(
                        allow_additional_maintenance
                        or not self._has_photos_on_calendar_day(reference_at)
                    ),
                    can_complete_maintenance=(
                        allow_additional_maintenance or not maintenance_completed_today
                    ),
                    revision_form_link=None,
                    loading_completed=self._loading_completed_for(
                        technician_id,
                        checked_at=reference_at,
                    ),
                    loading_photos_completed=self._has_photos_on_calendar_day(
                        reference_at,
                    ),
                    maintenance_completed_today=maintenance_completed_today,
                    responsibility_expires_at=calendar_anchor(
                        reference_at,
                        self.service_calendar_timezone,
                    ),
                    revision_due_status=None,
                )
            has_revision = self._last_revision is not None
            loading_completed = self._loading_completed_for(
                technician_id,
                checked_at=reference_at,
            )
            return ServiceCapabilities(
                technician_id=technician_id,
                machine_id=self.machine_id,
                responsibility_phase="responsible",
                can_complete_revision=False,
                can_submit_loading=True,
                can_submit_loading_photos=loading_completed
                and has_revision
                and (
                    allow_additional_maintenance
                    or not self._has_photos_on_calendar_day(reference_at)
                ),
                # ISS-018: complete ТО без loading_completed; фото/ревизия gated
                can_complete_maintenance=(
                    allow_additional_maintenance or not maintenance_completed_today
                ),
                revision_form_link=None,
                loading_completed=loading_completed,
                loading_photos_completed=(
                    has_revision and self._has_photos_on_calendar_day(reference_at)
                ),
                maintenance_completed_today=maintenance_completed_today,
                responsibility_expires_at=calendar_anchor(
                    reference_at,
                    self.service_calendar_timezone,
                ),
                revision_due_status=None,
            )

        if phase == "awaiting_handover":
            if revision_form_link is None and not allow_missing_revision_form:
                raise ValueError(
                    "revision_form_link is required for awaiting_handover phase",
                )
            if allow_missing_revision_form:
                reference_at = checked_at or datetime.now(tz=UTC)
                maintenance_completed_today = self._maintenance_completed_today(
                    checked_at=reference_at,
                )
                return ServiceCapabilities(
                    technician_id=technician_id,
                    machine_id=self.machine_id,
                    responsibility_phase=phase,
                    can_complete_revision=False,
                    can_submit_loading=False,
                    can_submit_loading_photos=(
                        allow_additional_maintenance
                        or not self._has_photos_on_calendar_day(reference_at)
                    ),
                    can_complete_maintenance=(
                        allow_additional_maintenance or not maintenance_completed_today
                    ),
                    revision_form_link=None,
                    loading_completed=self._loading_completed_for(
                        technician_id,
                        checked_at=reference_at,
                    ),
                    loading_photos_completed=self._has_photos_on_calendar_day(
                        reference_at,
                    ),
                    maintenance_completed_today=maintenance_completed_today,
                )
            loading_completed = self._loading_completed_for(
                technician_id,
                checked_at=checked_at,
            )
            can_complete_revision = revision_form_link is not None and loading_completed
            return ServiceCapabilities(
                technician_id=technician_id,
                machine_id=self.machine_id,
                responsibility_phase=phase,
                can_complete_revision=can_complete_revision,
                can_submit_loading=True,
                can_submit_loading_photos=False,
                can_complete_maintenance=False,
                revision_form_link=revision_form_link if can_complete_revision else None,
                loading_completed=loading_completed,
            )

        maintenance_completed_today = self._maintenance_completed_today(
            checked_at=checked_at,
        )
        loading_completed = self._loading_completed_for(
            technician_id,
            checked_at=checked_at,
        )
        can_submit_loading_photos = loading_completed and self._can_submit_loading_photos(
            technician_id,
            checked_at=checked_at,
            allow_additional_maintenance=allow_additional_maintenance,
        )
        return ServiceCapabilities(
            technician_id=technician_id,
            machine_id=self.machine_id,
            responsibility_phase=phase,
            can_complete_revision=False,
            can_submit_loading=True,
            can_submit_loading_photos=can_submit_loading_photos,
            # ISS-018: complete ТО без loading_completed; фото остаются gated
            can_complete_maintenance=(
                allow_additional_maintenance or not maintenance_completed_today
            ),
            revision_form_link=None,
            loading_completed=loading_completed,
            loading_photos_completed=self._loading_photos_completed_for(
                technician_id,
                checked_at=checked_at,
            ),
            maintenance_completed_today=maintenance_completed_today,
            responsibility_expires_at=self.responsibility_expires_at(),
            revision_due_status=self.revision_due_status(checked_at=checked_at),
        )

    @beartype
    def complete_revision(
        self,
        command: CompleteRevision,
    ) -> RevisionCompleted | RevisionNotAllowed:
        existing = self._revision_by_token.get(command.form_token)
        if existing is not None:
            return existing

        if not self._can_complete_revision(
            command.technician_id,
            checked_at=command.completed_at,
        ):
            return RevisionNotAllowed(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=REVISION_NOT_ALLOWED_REASON,
            )

        occurred_at = datetime.now(tz=UTC)
        revision_id = RevisionId(f"rev-{uuid.uuid4()}")
        responsibility_expires_at = None
        if (
            self.revision_interval_min_days is not None
            and self.revision_interval_max_days is not None
        ):
            responsibility_expires_at = compute_responsibility_expires_at(
                machine_id=self.machine_id,
                revision_id=revision_id,
                completed_at=command.completed_at,
                min_days=self.revision_interval_min_days,
                max_days=self.revision_interval_max_days,
                service_calendar_timezone=self.service_calendar_timezone,
            )
        event = RevisionCompleted(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            revision_id=revision_id,
            technician_id=command.technician_id,
            machine_id=self.machine_id,
            completed_at=command.completed_at,
            occurred_at=occurred_at,
            source=command.source,
            form_id=command.form_id,
            form_token=command.form_token,
            responsibility_expires_at=responsibility_expires_at,
        )
        self._record(event)
        return event

    @beartype
    def _loading_submission_allowed(self, command: SubmitLoading) -> bool:
        submitted_at = command.submitted_at
        technician_id = command.technician_id

        if self._holds_responsibility(technician_id, checked_at=submitted_at):
            if self._last_revision is None:
                return False
            return submitted_at >= self._last_revision.completed_at

        if self._awaiting_handover(technician_id, checked_at=submitted_at):
            if self._last_revision is None:
                return True
            return submitted_at > self._last_revision.completed_at

        return False

    @beartype
    def submit_loading(
        self,
        command: SubmitLoading,
    ) -> LoadingSubmitted | LoadingNotAllowed:
        if not self._loading_submission_allowed(command):
            return LoadingNotAllowed(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=LOADING_NOT_ALLOWED_REASON,
            )

        existing = self._loading_by_token.get(command.form_token)
        if existing is not None:
            return existing

        occurred_at = command.submitted_at
        event = LoadingSubmitted(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            technician_id=command.technician_id,
            machine_id=self.machine_id,
            submitted_at=command.submitted_at,
            occurred_at=occurred_at,
            form_id=command.form_id,
            form_token=command.form_token,
        )
        self._record(event)
        return event

    @beartype
    def submit_loading_photos(
        self,
        command: SubmitLoadingPhotos,
        *,
        skip_responsibility_check: bool = False,
        allow_additional_maintenance: bool = False,
        allow_missing_revision: bool = False,
    ) -> (
        PhotosSubmitted
        | LoadingPhotosNotAllowed
        | LoadingPhotosInsufficientCount
        | LoadingPhotosAlreadySubmittedToday
    ):
        existing = self._photos_by_batch_id.get(command.batch_id.value)
        if existing is not None:
            return existing

        if len(command.photos) < command.min_photo_count:
            return LoadingPhotosInsufficientCount(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON,
                min_photo_count=command.min_photo_count,
                actual_count=len(command.photos),
            )

        if (
            not allow_missing_revision
            and not skip_responsibility_check
            and not self._holds_responsibility(
                command.technician_id,
                checked_at=command.submitted_at,
            )
        ):
            return LoadingPhotosNotAllowed(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
            )

        if not allow_missing_revision:
            if self._last_revision is None:
                return LoadingPhotosNotAllowed(
                    technician_id=command.technician_id,
                    machine_id=self.machine_id,
                    reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
                )
            if command.submitted_at < self._last_revision.completed_at:
                return LoadingPhotosNotAllowed(
                    technician_id=command.technician_id,
                    machine_id=self.machine_id,
                    reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
                )

        if not allow_missing_revision and not self._loading_completed_for(
            command.technician_id,
            checked_at=command.submitted_at,
        ):
            return LoadingPhotosNotAllowed(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=LOADING_PHOTOS_REQUIRE_LOADING_REASON,
            )

        if self._has_photos_on_calendar_day(command.submitted_at) and (
            not allow_additional_maintenance
        ):
            return LoadingPhotosAlreadySubmittedToday(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
            )

        occurred_at = datetime.now(tz=UTC)
        maintenance_completed_at: datetime | None = None
        if allow_additional_maintenance or not self._has_maintenance_on_calendar_day(
            command.submitted_at,
        ):
            maintenance_completed_at = command.submitted_at
        event = PhotosSubmitted(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            batch_id=command.batch_id,
            technician_id=command.technician_id,
            machine_id=self.machine_id,
            photo_count=len(command.photos),
            submitted_at=command.submitted_at,
            occurred_at=occurred_at,
            maintenance_completed_at=maintenance_completed_at,
        )
        self._record(event)
        return event

    @beartype
    def last_loading_submitted_at(self) -> datetime | None:
        return self._last_loading_submitted_at

    @beartype
    def last_maintenance_completed_at(self) -> datetime | None:
        return self._last_maintenance_completed_at

    @beartype
    def complete_maintenance(
        self,
        command: CompleteMaintenance,
        *,
        checked_at: datetime | None = None,
        skip_responsibility_check: bool = False,
        allow_additional_maintenance: bool = False,
        allow_missing_revision: bool = False,
    ) -> MaintenanceCompleted | MaintenanceAlreadyCompletedToday | MaintenanceNotAllowed:
        if (
            not allow_missing_revision
            and not skip_responsibility_check
            and not self._holds_responsibility(
                command.technician_id,
                checked_at=checked_at,
            )
        ):
            return MaintenanceNotAllowed(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=MAINTENANCE_NOT_ALLOWED_REASON,
            )

        completed_at = command.completed_at
        reference_at = checked_at or completed_at

        # ISS-018: loading_completed больше не гейтит complete_maintenance
        # (фото / complete_revision по-прежнему требуют загрузку).

        if self._has_maintenance_on_calendar_day(reference_at) and (
            not allow_additional_maintenance
        ):
            return MaintenanceAlreadyCompletedToday(
                technician_id=command.technician_id,
                machine_id=self.machine_id,
                reason=MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
            )

        occurred_at = datetime.now(tz=UTC)
        event = MaintenanceCompleted(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            technician_id=command.technician_id,
            machine_id=self.machine_id,
            completed_at=completed_at,
            occurred_at=occurred_at,
        )
        self._record(event)
        return event

    @beartype
    def _responsibility_phase(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> ResponsibilityPhase:
        if self._holds_responsibility(technician_id, checked_at=checked_at):
            return "responsible"
        return "awaiting_handover"

    @beartype
    def _awaiting_handover(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> bool:
        return not self._holds_responsibility(technician_id, checked_at=checked_at)

    @beartype
    def _holds_responsibility(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> bool:
        """Несёт ли техник ответственность за этот аппарат прямо сейчас.

        Ответственный за интервал — техник, чья ревизия открыла период. Для
        текущего (открытого) периода это всегда техник последней ревизии,
        поэтому сравниваем `technician_id` с `_last_revision.technician_id`.
        Если период истёк (см. `_responsibility_period_expired`), ответственного
        нет — аппарат снова ждёт приёмки.
        """
        if self._last_revision is None:
            return False
        if self._last_revision.technician_id != technician_id:
            return False
        return not self._responsibility_period_expired(checked_at=checked_at)

    @beartype
    def _can_complete_revision(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> bool:
        if not self._awaiting_handover(technician_id, checked_at=checked_at):
            return False
        return self._loading_completed_for(technician_id, checked_at=checked_at)

    @beartype
    def _effective_responsibility_expires_at(self) -> datetime | None:
        if self._last_revision is None:
            return None
        if self._last_revision.responsibility_expires_at is not None:
            return self._last_revision.responsibility_expires_at
        if self.revision_interval_min_days is None:
            return None
        return self._last_revision.completed_at + timedelta(
            days=self.revision_interval_min_days,
        )

    @beartype
    def responsibility_expires_at(self) -> datetime | None:
        return self._effective_responsibility_expires_at()

    @beartype
    def revision_due_status(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> RevisionDueStatus | None:
        expires_at = self._effective_responsibility_expires_at()
        if expires_at is None:
            return None
        reference_at = checked_at or datetime.now(tz=UTC)
        return compute_revision_due_status(
            expires_at=expires_at,
            checked_at=reference_at,
        )

    @beartype
    def _responsibility_period_expired(self, *, checked_at: datetime | None = None) -> bool:
        """Закрылся ли период ответственности по hard deadline или legacy fallback."""
        if self._last_revision is None:
            return False

        status = self.revision_due_status(checked_at=checked_at)
        if status is not None:
            return status == "overdue"

        if self.revision_interval_min_days is None:
            return False

        reference_at = checked_at or datetime.now(tz=UTC)
        stale_at = self._last_revision.completed_at + timedelta(
            days=self.revision_interval_min_days,
        )
        return reference_at >= stale_at

    @beartype
    def _previous_revision_completed_at(self) -> datetime | None:
        if self._last_revision is None:
            return None
        previous: datetime | None = None
        for event in self._revision_by_token.values():
            if event.completed_at >= self._last_revision.completed_at:
                continue
            if previous is None or event.completed_at > previous:
                previous = event.completed_at
        return previous

    @beartype
    def _loading_completed_for(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> bool:
        """True if this technician submitted loading in the current operational day."""
        reference_at = checked_at or datetime.now(tz=UTC)
        return self._has_loading_on_operational_day(technician_id, reference_at)

    @beartype
    def _has_loading_on_operational_day(
        self,
        technician_id: TechnicianId,
        reference_at: datetime,
    ) -> bool:
        day = operational_day(
            reference_at,
            self.service_calendar_timezone,
            self.service_day_end_hour,
        )
        return any(
            loading.technician_id == technician_id
            and operational_day(
                loading.submitted_at,
                self.service_calendar_timezone,
                self.service_day_end_hour,
            )
            == day
            for loading in self._loading_by_token.values()
        )

    @beartype
    def _can_submit_loading_photos(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
        allow_additional_maintenance: bool = False,
    ) -> bool:
        if not self._holds_responsibility(technician_id, checked_at=checked_at):
            return False

        reference_at = checked_at or datetime.now(tz=UTC)
        if allow_additional_maintenance:
            return True
        return not self._has_photos_on_calendar_day(reference_at)

    @beartype
    def _loading_photos_completed_for(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> bool:
        if not self._holds_responsibility(technician_id, checked_at=checked_at):
            return False

        reference_at = checked_at or datetime.now(tz=UTC)
        return self._has_photos_on_calendar_day(reference_at)

    @beartype
    def _has_photos_on_calendar_day(self, reference_at: datetime) -> bool:
        day = operational_day(
            reference_at,
            self.service_calendar_timezone,
            self.service_day_end_hour,
        )
        return day in self._photos_submitted_days

    @beartype
    def _maintenance_completed_today(self, *, checked_at: datetime | None = None) -> bool:
        reference_at = checked_at or datetime.now(tz=UTC)
        return self._has_maintenance_on_calendar_day(reference_at)

    @beartype
    def _has_maintenance_on_calendar_day(self, reference_at: datetime) -> bool:
        day = operational_day(
            reference_at,
            self.service_calendar_timezone,
            self.service_day_end_hour,
        )
        return day in self._maintenance_completed_days

    @beartype
    def collect_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    @beartype
    def clear_pending_events(self) -> None:
        self._pending_events.clear()

    @beartype
    def _record(self, event: DomainEvent) -> None:
        self._apply(event)
        self._pending_events.append(event)

    @beartype
    def _apply(self, event: DomainEvent) -> None:
        if isinstance(event, RevisionCompleted):
            self._revision_by_token[event.form_token] = event
            snapshot = _revision_snapshot_from_event(event)
            if self._last_revision is None or (
                snapshot.completed_at > self._last_revision.completed_at
            ):
                self._last_revision = snapshot
            return

        if isinstance(event, LoadingSubmitted):
            self._loading_by_token[event.form_token] = event
            if (
                self._last_loading_submitted_at is None
                or event.submitted_at > self._last_loading_submitted_at
            ):
                self._last_loading_submitted_at = event.submitted_at
            return

        if isinstance(event, PhotosSubmitted):
            self._photos_by_batch_id[event.batch_id.value] = event
            day = operational_day(
                event.submitted_at,
                self.service_calendar_timezone,
                self.service_day_end_hour,
            )
            self._photos_submitted_days.add(day)
            if event.maintenance_completed_at is not None:
                maintenance_day = operational_day(
                    event.maintenance_completed_at,
                    self.service_calendar_timezone,
                    self.service_day_end_hour,
                )
                self._maintenance_completed_days.add(maintenance_day)
                if (
                    self._last_maintenance_completed_at is None
                    or event.maintenance_completed_at > self._last_maintenance_completed_at
                ):
                    self._last_maintenance_completed_at = event.maintenance_completed_at
            return

        if isinstance(event, MaintenanceCompleted):
            day = operational_day(
                event.completed_at,
                self.service_calendar_timezone,
                self.service_day_end_hour,
            )
            self._maintenance_completed_days.add(day)
            if (
                self._last_maintenance_completed_at is None
                or event.completed_at > self._last_maintenance_completed_at
            ):
                self._last_maintenance_completed_at = event.completed_at
            return


@beartype
def _revision_snapshot_from_event(event: RevisionCompleted) -> RevisionSnapshot:
    return RevisionSnapshot(
        revision_id=event.revision_id,
        technician_id=event.technician_id,
        completed_at=event.completed_at,
        source=event.source,
        form_id=event.form_id,
        form_token=event.form_token,
        responsibility_expires_at=event.responsibility_expires_at,
    )
