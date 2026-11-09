from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE, operational_day
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.ids import TechnicianId as TechId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.models import VendingMachine
from src.domain.photo_batch import PhotoRef
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.interfaces.telegram.loading_photos_outbox import LoadingPhotosTelegramOutboxHandler

_BATCH_ID = BatchId("batch-telegram-1")
_EVENT_ID = EventId("event-telegram-1")
_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


class _FakeVendingMachineRepository:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name="ТЦ Мега, ряд 2")

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return "Иванов И."

    def find_technician_display_name(
        self,
        technician_id: TechId,
    ) -> str | None:
        return "Иванов И."

    def list_available_for_technician(
        self,
        technician_id: TechId,
    ) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechId | None:
        return None


class _RecordingNotifier:
    def __init__(self, *, message_ids: tuple[int, ...] = (101, 102)) -> None:
        self.calls = 0
        self.last_kwargs: dict[str, object] | None = None
        self._message_ids = message_ids

    async def notify_batch(self, **kwargs: object) -> tuple[int, ...]:
        self.calls += 1
        self.last_kwargs = kwargs
        return self._message_ids


class _SplitTechnicianNameRepository(_FakeVendingMachineRepository):
    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return "Иванов И."

    def find_technician_display_name(
        self,
        technician_id: TechId,
    ) -> str | None:
        if technician_id.value == "tech-submitter":
            return "Петров П."
        return "Иванов И."


def _accepted_snapshot(store: InMemoryPhotoBatchStore) -> None:
    store.save_pending(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="u-1",
                message_id=1,
            ),
        ),
    )
    store.mark_accepted(
        _BATCH_ID,
        event_id=_EVENT_ID.value,
        occurred_at=_SUBMITTED_AT,
    )


def _event() -> PhotosSubmitted:
    return PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )


def test_loading_photos_caption_uses_previous_operational_day() -> None:
    # edge: 05:30 МСК при day_end_hour=6 → предыдущий ops day
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    notifier = _RecordingNotifier()
    tz = ZoneInfo("Europe/Moscow")
    submitted = datetime(2026, 5, 20, 2, 30, tzinfo=UTC)  # 05:30 МСК
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=tz,
        day_end_hour=6,
        enabled=True,
    )
    event = PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=1,
        submitted_at=submitted,
        occurred_at=submitted,
    )
    asyncio.run(handler.process(event))
    expected = operational_day(submitted, tz, 6).strftime("%d.%m.%Y")
    assert expected == "19.05.2026"
    assert notifier.last_kwargs is not None
    assert notifier.last_kwargs["calendar_day_label"] == expected


def test_loading_photos_telegram_outbox_uses_submitter_display_name() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    notifier = _RecordingNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_SplitTechnicianNameRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )
    event = PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=TechnicianId("tech-submitter"),
        machine_id=_MACHINE,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )

    asyncio.run(handler.process(event))

    assert notifier.last_kwargs is not None
    assert notifier.last_kwargs["technician_display_name"] == "Петров П."


def test_loading_photos_telegram_outbox_sends_and_persists_message_ids() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    notifier = _RecordingNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )

    asyncio.run(handler.process(_event()))

    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.proxy_message_ids == (101, 102)
    assert notifier.calls == 1


def test_loading_photos_telegram_outbox_persists_all_chunk_message_ids() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    chunk_message_ids = tuple(range(600, 615))
    notifier = _RecordingNotifier(message_ids=chunk_message_ids)
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )

    asyncio.run(handler.process(_event()))

    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.proxy_message_ids == chunk_message_ids
    assert notifier.calls == 1


def test_loading_photos_telegram_outbox_is_idempotent() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    notifier = _RecordingNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )
    event = _event()

    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))

    assert notifier.calls == 1


def test_loading_photos_telegram_outbox_skips_when_disabled() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    notifier = _RecordingNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=False,
    )

    asyncio.run(handler.process(_event()))

    assert notifier.calls == 0


def test_loading_photos_telegram_outbox_skips_when_proxy_message_ids_set() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)
    store.update_proxy_message_ids(_BATCH_ID, (999,))
    notifier = _RecordingNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )

    asyncio.run(handler.process(_event()))

    assert notifier.calls == 0
    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.proxy_message_ids == (999,)


def test_loading_photos_telegram_outbox_skips_when_notifier_returns_empty() -> None:
    store = InMemoryPhotoBatchStore()
    _accepted_snapshot(store)

    class _EmptyNotifier:
        def __init__(self) -> None:
            self.calls = 0

        async def notify_batch(self, **kwargs: object) -> tuple[int, ...]:
            self.calls += 1
            return ()

    notifier = _EmptyNotifier()
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(notifier),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )

    asyncio.run(handler.process(_event()))

    assert notifier.calls == 1
    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.proxy_message_ids == ()
