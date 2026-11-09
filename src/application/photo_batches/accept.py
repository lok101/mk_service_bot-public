from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.machine_operations import (
    RegisterLoadingPhotos,
    SubmitLoadingPhotosCommand,
    SubmitLoadingPhotosResult,
)
from src.application.photo_batches.errors import PhotoBatchRejectedError
from src.application.photo_batches.loading_photos_limits import (
    LoadingPhotosMachineKindLookup,
    LoadingPhotosProfileLookup,
    resolve_loading_photos_cues,
)
from src.application.photo_batches.ports import PhotoBatchStore
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef
from src.domain.results import loading_photos_excess_count_reason

_FALLBACK_COFFEE_CHECKLIST: tuple[str, ...] = (
    "1. Общий план ДО.",
    "2. Органайзер.",
    "3. Открытая машина.",
    "4. Открытый шкаф под машиной.",
    "5. Мусорное ведро, ведро жидких отходов, контейнер твердых отходов.",
    "6. Лоток и миксеры (разобранные и мытые).",
    "7. Сиропы.",
    "8. Работающий терминал.",
    "9. График визитов.",
    "10. Общий план ПОСЛЕ.",
)
_PROFILE_MISSING_REASON = "Для аппарата не настроен профиль фото. Обратитесь к координатору."


@beartype
def _photos_submitted_from_snapshot(snapshot: PhotoBatchSnapshot) -> PhotosSubmitted:
    if snapshot.event_id is None or snapshot.occurred_at is None:
        raise ValueError("Accepted photo batch snapshot must include event_id and occurred_at")

    return PhotosSubmitted(
        event_id=EventId(snapshot.event_id),
        batch_id=snapshot.batch_id,
        technician_id=snapshot.technician_id,
        machine_id=snapshot.machine_id,
        photo_count=len(snapshot.photos),
        submitted_at=snapshot.submitted_at,
        occurred_at=snapshot.occurred_at,
    )


@beartype
@dataclass(frozen=True, slots=True)
class AcceptLoadingPhotosService:
    photo_batch_store: PhotoBatchStore
    register_loading_photos: RegisterLoadingPhotos
    loading_photos_min_count: int
    loading_photos_max_count: int
    machine_kind_lookup: LoadingPhotosMachineKindLookup | None = None
    profile_lookup: LoadingPhotosProfileLookup | None = None
    profile_strict: bool = False

    def __post_init__(self) -> None:
        if self.loading_photos_min_count < 1:
            raise ValueError("loading_photos_min_count must be at least 1")
        if self.loading_photos_max_count < 1:
            raise ValueError("loading_photos_max_count must be at least 1")
        if self.loading_photos_max_count < self.loading_photos_min_count:
            raise ValueError(
                "loading_photos_max_count must be greater than or equal to "
                "loading_photos_min_count",
            )

    @beartype
    def _limits_for_machine(self, machine_id: MachineId) -> tuple[int, int]:
        min_count, max_count, _checklist, _mm, missing = resolve_loading_photos_cues(
            machine_code=machine_id.value,
            coffee_min=self.loading_photos_min_count,
            coffee_max=self.loading_photos_max_count,
            kind_lookup=self.machine_kind_lookup,
            profile_lookup=self.profile_lookup,
            profile_strict=self.profile_strict,
            coffee_checklist=_FALLBACK_COFFEE_CHECKLIST,
        )
        if missing:
            raise PhotoBatchRejectedError(_PROFILE_MISSING_REASON)
        return min_count, max_count

    @beartype
    def execute(
        self,
        *,
        batch_id: BatchId,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        photos: tuple[PhotoRef, ...],
    ) -> PhotosSubmitted:
        existing = self.photo_batch_store.get_by_batch_id(batch_id)
        if existing is not None and existing.status == "accepted":
            return _photos_submitted_from_snapshot(existing)

        min_count, max_count = self._limits_for_machine(machine_id)
        if len(photos) > max_count:
            raise PhotoBatchRejectedError(
                loading_photos_excess_count_reason(max_count),
            )

        self.photo_batch_store.save_pending(
            batch_id=batch_id,
            purpose="loading",
            technician_id=technician_id,
            machine_id=machine_id,
            submitted_at=submitted_at,
            photos=photos,
        )
        result = self.register_loading_photos.execute(
            SubmitLoadingPhotosCommand(
                technician_id=technician_id,
                machine_id=machine_id,
                batch_id=batch_id,
                submitted_at=submitted_at,
                photos=photos,
                min_photo_count=min_count,
            ),
        )
        return self._finalize(batch_id, result)

    @beartype
    def _finalize(
        self,
        batch_id: BatchId,
        result: SubmitLoadingPhotosResult,
    ) -> PhotosSubmitted:
        if isinstance(result, PhotosSubmitted):
            self.photo_batch_store.mark_accepted(
                batch_id,
                event_id=result.event_id.value,
                occurred_at=result.occurred_at,
            )
            return result

        # All rejection variants of SubmitLoadingPhotosResult share .reason
        # (incl. LoadingPhotosBlocked; not on barrel — use_cases import forbidden).
        self.photo_batch_store.mark_rejected(batch_id, reason=result.reason)
        raise PhotoBatchRejectedError(result.reason)
