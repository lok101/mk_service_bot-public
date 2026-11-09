from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.photo_batches.ports import PhotoBatchStore
from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.finding_id import deterministic_photo_integrity_finding_id
from src.application.photo_integrity.ports import (
    PhotoContentHashEntry,
    PhotoContentHashIndex,
    PhotoDuplicateAccountabilityRecorder,
    PhotoIntegrityFindingStore,
)
from src.domain.ids import BatchId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoBatchSnapshot
from src.domain.photo_integrity import PhotoIntegrityFinding


@beartype
@dataclass(frozen=True, slots=True)
class ProcessLoadingPhotosIntegrity:
    hash_index: PhotoContentHashIndex
    finding_store: PhotoIntegrityFindingStore
    accountability: PhotoDuplicateAccountabilityRecorder
    photo_batch_store: PhotoBatchStore
    alerter: PhotoIntegrityDuplicateAlerter

    @beartype
    async def execute(self, *, event: PhotosSubmitted, snapshot: PhotoBatchSnapshot) -> None:
        detected_at = datetime.now(tz=UTC)
        for index, stored in enumerate(snapshot.stored_files):
            await self._process_photo(
                event=event,
                snapshot_batch_id=snapshot.batch_id,
                index=index,
                content_hash=stored.content_hash,
                storage_key=stored.storage_key,
                file_unique_id=snapshot.photos[index].file_unique_id,
                file_id=snapshot.photos[index].file_id,
                detected_at=detected_at,
            )

    @beartype
    async def _process_photo(
        self,
        *,
        event: PhotosSubmitted,
        snapshot_batch_id: BatchId,
        index: int,
        content_hash: str,
        storage_key: str,
        file_unique_id: str,
        file_id: str,
        detected_at: datetime,
    ) -> None:
        existing_pending = await asyncio.to_thread(
            self.finding_store.find_pending,
            batch_id=snapshot_batch_id,
            photo_index=index,
            content_hash=content_hash,
        )
        if existing_pending is not None and existing_pending.alert_sent_at is not None:
            return

        matched: PhotoContentHashEntry | None
        finding: PhotoIntegrityFinding

        if existing_pending is not None:
            finding = existing_pending
            matched = self._lookup_hash_entry(content_hash, file_unique_id)
            if matched is None:
                matched = PhotoContentHashEntry(
                    content_hash=content_hash,
                    telegram_file_unique_id=file_unique_id,
                    first_batch_id=finding.matched_batch_id,
                    first_technician_id=event.technician_id,
                    first_machine_id=event.machine_id,
                    first_submitted_at=event.submitted_at,
                    storage_key=storage_key,
                    photo_index=index,
                )
        else:
            matched = self._find_duplicate(
                content_hash=content_hash,
                file_unique_id=file_unique_id,
                current_batch_id=snapshot_batch_id,
            )
            if matched is None:
                inserted = await asyncio.to_thread(
                    self.hash_index.insert_first_seen,
                    PhotoContentHashEntry(
                        content_hash=content_hash,
                        telegram_file_unique_id=file_unique_id,
                        first_batch_id=snapshot_batch_id,
                        first_technician_id=event.technician_id,
                        first_machine_id=event.machine_id,
                        first_submitted_at=event.submitted_at,
                        storage_key=storage_key,
                        photo_index=index,
                    ),
                )
                if inserted:
                    return
                raced = self._lookup_hash_entry(content_hash, file_unique_id)
                if raced is None or raced.first_batch_id == snapshot_batch_id:
                    return
                matched = raced

            finding = PhotoIntegrityFinding(
                finding_id=deterministic_photo_integrity_finding_id(
                    batch_id=snapshot_batch_id,
                    photo_index=index,
                    content_hash=content_hash,
                ),
                status="pending_review",
                new_batch_id=snapshot_batch_id,
                matched_batch_id=matched.first_batch_id,
                technician_id=event.technician_id,
                content_hash=content_hash,
                photo_index=index,
                detected_at=detected_at,
            )
            await asyncio.to_thread(self.finding_store.save, finding)
            await asyncio.to_thread(
                self.accountability.record_duplicate_suspected,
                technician_id=event.technician_id,
                finding_id=finding.finding_id,
                new_batch_id=snapshot_batch_id,
                matched_batch_id=matched.first_batch_id,
                new_machine_id=event.machine_id,
                matched_machine_id=matched.first_machine_id,
                content_hash=content_hash,
                photo_index=index,
                detected_at=detected_at,
            )

        await self._send_duplicate_alert(
            event=event,
            finding=finding,
            matched=matched,
            file_id=file_id,
        )
        await asyncio.to_thread(
            self.finding_store.mark_alert_sent,
            finding.finding_id,
            datetime.now(tz=UTC),
        )

    @beartype
    async def _send_duplicate_alert(
        self,
        *,
        event: PhotosSubmitted,
        finding: PhotoIntegrityFinding,
        matched: PhotoContentHashEntry,
        file_id: str,
    ) -> None:
        matched_snapshot = await asyncio.to_thread(
            self.photo_batch_store.get_by_batch_id,
            matched.first_batch_id,
        )
        matched_file_id: str | None = None
        if matched_snapshot is not None and matched.photo_index < len(matched_snapshot.photos):
            matched_file_id = matched_snapshot.photos[matched.photo_index].file_id

        await self.alerter.notify(
            event=event,
            finding=finding,
            matched=matched,
            new_photo_file_id=file_id,
            matched_photo_file_id=matched_file_id,
        )

    @beartype
    def _lookup_hash_entry(
        self,
        content_hash: str,
        file_unique_id: str,
    ) -> PhotoContentHashEntry | None:
        by_hash = self.hash_index.find_by_content_hash(content_hash)
        if by_hash is not None:
            return by_hash
        return self.hash_index.find_by_file_unique_id(file_unique_id)

    @beartype
    def _find_duplicate(
        self,
        *,
        content_hash: str,
        file_unique_id: str,
        current_batch_id: BatchId,
    ) -> PhotoContentHashEntry | None:
        by_hash = self.hash_index.find_by_content_hash(content_hash)
        if by_hash is not None and by_hash.first_batch_id != current_batch_id:
            return by_hash

        by_unique = self.hash_index.find_by_file_unique_id(file_unique_id)
        if by_unique is not None and by_unique.first_batch_id != current_batch_id:
            return by_unique
        return None
