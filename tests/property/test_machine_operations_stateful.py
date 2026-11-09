from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from src.domain.calendar import (
    DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    operational_day,
)
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    DomainEvent,
    LoadingSubmitted,
    MachineOperations,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
    SubmitLoading,
    SubmitLoadingPhotos,
)
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.results import (
    LoadingNotAllowed,
    LoadingPhotosAlreadySubmittedToday,
    LoadingPhotosNotAllowed,
    MaintenanceAlreadyCompletedToday,
    MaintenanceNotAllowed,
    RevisionNotAllowed,
    ServiceCapabilities,
)
from src.domain.revision_due_policy import compute_responsibility_expires_at

from .strategies import TOKEN

TECHNICIAN = st.sampled_from((TechnicianId("tech-a"), TechnicianId("tech-b")))
_MSK = ZoneInfo("Europe/Moscow")
OPERATIONAL_BOUNDARY_TIMES = st.sampled_from(
    (
        datetime(2026, 6, 1, 5, 59, tzinfo=_MSK),
        datetime(2026, 6, 1, 6, 0, tzinfo=_MSK),
    )
)
_BOUNDARY_TIMES = (
    datetime(2026, 6, 1, 5, 59, tzinfo=_MSK),
    datetime(2026, 6, 1, 6, 0, tzinfo=_MSK),
)
_TECHS = (TechnicianId("tech-a"), TechnicianId("tech-b"))
_MACHINE_ID = MachineId("vm-property")
_REVISION_FORM_LINK = PrefilledFormLink(url="https://example.com/forms/revision")
_PHOTOS = (
    PhotoRef(file_id="f1", file_unique_id="u1", message_id=1),
    PhotoRef(file_id="f2", file_unique_id="u2", message_id=2),
)
_TZ = DEFAULT_SERVICE_CALENDAR_TIMEZONE
_DAY_END = 6
_MIN_DAYS = 1
_MAX_DAYS = 1


def _ops_day(moment: datetime) -> date:
    return operational_day(moment, _TZ, _DAY_END)


def _cap_tuple(caps: ServiceCapabilities) -> tuple[object, ...]:
    return (
        caps.responsibility_phase,
        caps.can_complete_revision,
        caps.can_submit_loading,
        caps.can_submit_loading_photos,
        caps.can_complete_maintenance,
        caps.loading_completed,
        caps.loading_photos_completed,
        caps.maintenance_completed_today,
        caps.revision_due_status,
        caps.revision_form_link is not None,
    )


def machine_view(aggregate: MachineOperations) -> tuple[object, ...]:
    caps = {
        (tech.value, at.isoformat()): _cap_tuple(
            aggregate.get_service_capabilities(
                tech,
                checked_at=at,
                revision_form_link=_REVISION_FORM_LINK,
            )
        )
        for tech in _TECHS
        for at in _BOUNDARY_TIMES
    }
    return (
        aggregate.last_revision_opened_by(),
        aggregate.last_revision_opened_at(),
        aggregate.last_maintenance_completed_at(),
        aggregate.last_loading_submitted_at(),
        caps,
    )


@dataclass(slots=True)
class MachineOracle:
    """Independent mutable oracle for MachineOperations public view."""

    last_revision_owner: TechnicianId | None = None
    last_revision_at: datetime | None = None
    last_revision_id: object | None = None
    prev_revision_at: datetime | None = None
    responsibility_expires_at: datetime | None = None
    revision_tokens: set[str] = field(default_factory=set)
    loading_tokens: set[str] = field(default_factory=set)
    photo_batches: set[str] = field(default_factory=set)
    photos_days: set[date] = field(default_factory=set)
    maintenance_days: set[date] = field(default_factory=set)
    last_loading_submitted_at: datetime | None = None
    last_maintenance_completed_at: datetime | None = None
    loadings: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    def note_revision(self, event: RevisionCompleted) -> None:
        if event.form_token in self.revision_tokens:
            return
        self.revision_tokens.add(event.form_token)
        if self.last_revision_at is None or event.completed_at > self.last_revision_at:
            self.prev_revision_at = self.last_revision_at
            self.last_revision_owner = event.technician_id
            self.last_revision_at = event.completed_at
            self.last_revision_id = event.revision_id
            self.responsibility_expires_at = event.responsibility_expires_at

    def note_loading(self, event: LoadingSubmitted) -> None:
        if event.form_token in self.loading_tokens:
            return
        self.loading_tokens.add(event.form_token)
        self.loadings.append((event.technician_id, event.submitted_at))
        if (
            self.last_loading_submitted_at is None
            or event.submitted_at > self.last_loading_submitted_at
        ):
            self.last_loading_submitted_at = event.submitted_at

    def note_photos(self, event: PhotosSubmitted) -> None:
        if event.batch_id.value in self.photo_batches:
            return
        self.photo_batches.add(event.batch_id.value)
        self.photos_days.add(_ops_day(event.submitted_at))
        if event.maintenance_completed_at is not None:
            completed_at = event.maintenance_completed_at
            self.maintenance_days.add(_ops_day(completed_at))
            if (
                self.last_maintenance_completed_at is None
                or completed_at > self.last_maintenance_completed_at
            ):
                self.last_maintenance_completed_at = completed_at

    def note_maintenance(self, event: MaintenanceCompleted) -> None:
        day = _ops_day(event.completed_at)
        if (
            day in self.maintenance_days
            and self.last_maintenance_completed_at is not None
            and event.completed_at <= self.last_maintenance_completed_at
        ):
            return
        self.maintenance_days.add(day)
        if (
            self.last_maintenance_completed_at is None
            or event.completed_at > self.last_maintenance_completed_at
        ):
            self.last_maintenance_completed_at = event.completed_at

    def _phase(self, technician_id: TechnicianId, checked_at: datetime) -> str:
        if self.last_revision_owner is None or self.last_revision_at is None:
            return "awaiting_handover"
        expires = self.responsibility_expires_at
        if expires is None:
            expires = self.last_revision_at + timedelta(days=_MIN_DAYS)
        if checked_at >= expires:
            return "awaiting_handover"
        if technician_id == self.last_revision_owner:
            return "responsible"
        return "awaiting_handover"

    def _loading_completed(self, technician_id: TechnicianId, checked_at: datetime) -> bool:
        day = _ops_day(checked_at)
        return any(
            tech == technician_id and _ops_day(submitted_at) == day
            for tech, submitted_at in self.loadings
        )

    def _due_status(self, checked_at: datetime) -> str | None:
        if self.last_revision_at is None or self.last_revision_id is None:
            return None
        expires = self.responsibility_expires_at
        if expires is None:
            expires = compute_responsibility_expires_at(
                machine_id=_MACHINE_ID,
                revision_id=self.last_revision_id,
                completed_at=self.last_revision_at,
                min_days=_MIN_DAYS,
                max_days=_MAX_DAYS,
                service_calendar_timezone=_TZ,
            )
        if checked_at >= expires:
            return "overdue"
        return "not_due"

    def _caps_for(
        self,
        technician_id: TechnicianId,
        checked_at: datetime,
    ) -> tuple[object, ...]:
        phase = self._phase(technician_id, checked_at)
        day = _ops_day(checked_at)
        maintenance_today = day in self.maintenance_days
        photos_today = day in self.photos_days
        loading_completed = self._loading_completed(technician_id, checked_at)
        has_revision = self.last_revision_at is not None
        if phase == "awaiting_handover":
            can_complete_revision = loading_completed
            return (
                phase,
                can_complete_revision,
                True,
                False,
                False,
                loading_completed,
                False,
                False,
                None,
                can_complete_revision,
            )
        due_status = self._due_status(checked_at)
        can_submit_photos = loading_completed and has_revision and not photos_today
        # ISS-018: complete ТО без loading_completed; фото по-прежнему gated
        return (
            phase,
            False,
            True,
            can_submit_photos,
            not maintenance_today,
            loading_completed,
            photos_today,
            maintenance_today,
            due_status,
            False,
        )

    def view(self) -> tuple[object, ...]:
        caps = {
            (tech.value, at.isoformat()): self._caps_for(tech, at)
            for tech in _TECHS
            for at in _BOUNDARY_TIMES
        }
        return (
            self.last_revision_owner,
            self.last_revision_at,
            self.last_maintenance_completed_at,
            self.last_loading_submitted_at,
            caps,
        )


class MachineOperationsStateMachine(RuleBasedStateMachine):
    @initialize()
    def initialize(self) -> None:
        self.aggregate = MachineOperations.empty(
            _MACHINE_ID,
            revision_interval_min_days=_MIN_DAYS,
            revision_interval_max_days=_MAX_DAYS,
            service_calendar_timezone=_TZ,
            service_day_end_hour=_DAY_END,
        )
        self.events: list[DomainEvent] = []
        self.oracle = MachineOracle()

    def _commit_pending(self) -> None:
        pending = self.aggregate.collect_events()
        assert len(pending) <= 1
        self.events.extend(pending)
        self.aggregate.clear_pending_events()

    @rule(token=TOKEN, technician=TECHNICIAN, at=OPERATIONAL_BOUNDARY_TIMES)
    def complete_revision(
        self,
        token: str,
        technician: TechnicianId,
        at: datetime,
    ) -> None:
        before = machine_view(self.aggregate)
        result = self.aggregate.complete_revision(
            CompleteRevision(
                technician_id=technician,
                completed_at=at,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token=token,
            ),
        )
        if isinstance(result, RevisionNotAllowed):
            assert self.aggregate.collect_events() == []
            assert machine_view(self.aggregate) == before
            return
        assert isinstance(result, RevisionCompleted)
        pending = self.aggregate.collect_events()
        if pending:
            assert pending == [result]
            self.oracle.note_revision(result)
            self._commit_pending()
        else:
            assert result.form_token in self.oracle.revision_tokens

    @rule(token=TOKEN, technician=TECHNICIAN, at=OPERATIONAL_BOUNDARY_TIMES)
    def submit_loading(
        self,
        token: str,
        technician: TechnicianId,
        at: datetime,
    ) -> None:
        before = machine_view(self.aggregate)
        result = self.aggregate.submit_loading(
            SubmitLoading(
                technician_id=technician,
                submitted_at=at,
                form_id="form-loading",
                form_token=token,
            ),
        )
        if isinstance(result, LoadingNotAllowed):
            assert self.aggregate.collect_events() == []
            assert machine_view(self.aggregate) == before
            return
        assert isinstance(result, LoadingSubmitted)
        pending = self.aggregate.collect_events()
        if pending:
            assert pending == [result]
            self.oracle.note_loading(result)
            self._commit_pending()
        else:
            assert result.form_token in self.oracle.loading_tokens

    @rule(batch_id=TOKEN, technician=TECHNICIAN, at=OPERATIONAL_BOUNDARY_TIMES)
    def submit_photos(
        self,
        batch_id: str,
        technician: TechnicianId,
        at: datetime,
    ) -> None:
        before = machine_view(self.aggregate)
        result = self.aggregate.submit_loading_photos(
            SubmitLoadingPhotos(
                technician_id=technician,
                batch_id=BatchId(batch_id),
                submitted_at=at,
                photos=_PHOTOS,
                min_photo_count=2,
            ),
        )
        if isinstance(
            result,
            (LoadingPhotosNotAllowed, LoadingPhotosAlreadySubmittedToday),
        ):
            assert self.aggregate.collect_events() == []
            assert machine_view(self.aggregate) == before
            return
        assert isinstance(result, PhotosSubmitted)
        pending = self.aggregate.collect_events()
        if pending:
            assert pending == [result]
            self.oracle.note_photos(result)
            self._commit_pending()
        else:
            assert result.batch_id.value in self.oracle.photo_batches

    @rule(technician=TECHNICIAN, at=OPERATIONAL_BOUNDARY_TIMES)
    def complete_maintenance(
        self,
        technician: TechnicianId,
        at: datetime,
    ) -> None:
        before = machine_view(self.aggregate)
        result = self.aggregate.complete_maintenance(
            CompleteMaintenance(technician_id=technician, completed_at=at),
            checked_at=at,
        )
        if isinstance(
            result,
            (MaintenanceNotAllowed, MaintenanceAlreadyCompletedToday),
        ):
            assert self.aggregate.collect_events() == []
            assert machine_view(self.aggregate) == before
            return
        assert isinstance(result, MaintenanceCompleted)
        pending = self.aggregate.collect_events()
        assert pending == [result]
        self.oracle.note_maintenance(result)
        self._commit_pending()

    @invariant()
    def live_and_replayed_views_match_oracle(self) -> None:
        all_events = [*self.events, *self.aggregate.collect_events()]
        replayed = MachineOperations.rehydrate(
            self.aggregate.machine_id,
            all_events,
            revision_interval_min_days=_MIN_DAYS,
            revision_interval_max_days=_MAX_DAYS,
            service_calendar_timezone=_TZ,
            service_day_end_hour=_DAY_END,
        )
        assert machine_view(self.aggregate) == machine_view(replayed) == self.oracle.view()


class TestMachineOperationsStateMachine(MachineOperationsStateMachine.TestCase):
    settings = settings(
        max_examples=100,
        stateful_step_count=50,
        deadline=None,
    )


def test_photo_driven_maintenance_is_one_event_and_replays_across_day_boundary() -> None:
    aggregate = MachineOperations.empty(
        _MACHINE_ID,
        revision_interval_min_days=_MIN_DAYS,
        revision_interval_max_days=_MAX_DAYS,
        service_calendar_timezone=_TZ,
        service_day_end_hour=_DAY_END,
    )
    before_boundary = datetime(2026, 6, 1, 5, 59, tzinfo=_MSK)
    after_boundary = datetime(2026, 6, 1, 6, 0, tzinfo=_MSK)
    tech = TechnicianId("tech-a")

    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=tech,
            submitted_at=before_boundary - timedelta(minutes=1),
            form_id="form-loading",
            form_token="token-load-boundary",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    events = list(aggregate.collect_events())
    aggregate.clear_pending_events()

    revision = aggregate.complete_revision(
        CompleteRevision(
            technician_id=tech,
            completed_at=before_boundary,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-boundary",
        ),
    )
    assert isinstance(revision, RevisionCompleted)
    events.extend(aggregate.collect_events())
    aggregate.clear_pending_events()

    photo = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=tech,
            batch_id=BatchId("batch-boundary"),
            submitted_at=before_boundary,
            photos=_PHOTOS,
            min_photo_count=2,
        ),
    )
    assert isinstance(photo, PhotosSubmitted)
    assert photo.maintenance_completed_at == before_boundary
    photo_events = list(aggregate.collect_events())
    assert len(photo_events) == 1
    aggregate.clear_pending_events()

    replayed = MachineOperations.rehydrate(
        _MACHINE_ID,
        [*events, *photo_events],
        revision_interval_min_days=_MIN_DAYS,
        revision_interval_max_days=_MAX_DAYS,
        service_calendar_timezone=_TZ,
        service_day_end_hour=_DAY_END,
    )
    assert replayed.last_maintenance_completed_at() == before_boundary
    caps_before = replayed.get_service_capabilities(
        tech,
        checked_at=before_boundary,
        revision_form_link=_REVISION_FORM_LINK,
    )
    caps_after = replayed.get_service_capabilities(
        tech,
        checked_at=after_boundary,
        revision_form_link=_REVISION_FORM_LINK,
    )
    assert caps_before.maintenance_completed_today is True
    assert caps_after.maintenance_completed_today is False

    duplicate = replayed.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=tech,
            batch_id=BatchId("batch-boundary"),
            submitted_at=after_boundary,
            photos=_PHOTOS,
            min_photo_count=2,
        ),
    )
    assert duplicate is photo
    assert replayed.collect_events() == []
