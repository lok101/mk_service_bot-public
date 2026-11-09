from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from beartype import beartype

from src.application.photo_integrity.ports import PhotoContentHashEntry
from src.domain.ids import BatchId, FindingId
from src.domain.photo_integrity import PhotoIntegrityFinding


@beartype
@dataclass
class InMemoryPhotoContentHashIndex:
    _by_hash: dict[str, PhotoContentHashEntry] = field(default_factory=dict)
    _by_file_unique_id: dict[str, PhotoContentHashEntry] = field(default_factory=dict)

    @beartype
    def find_by_content_hash(self, content_hash: str) -> PhotoContentHashEntry | None:
        return self._by_hash.get(content_hash)

    @beartype
    def find_by_file_unique_id(self, file_unique_id: str) -> PhotoContentHashEntry | None:
        return self._by_file_unique_id.get(file_unique_id)

    @beartype
    def insert_first_seen(self, entry: PhotoContentHashEntry) -> bool:
        if entry.content_hash in self._by_hash:
            return False
        self._by_hash[entry.content_hash] = entry
        self._by_file_unique_id[entry.telegram_file_unique_id] = entry
        return True


@beartype
@dataclass
class InMemoryPhotoIntegrityFindingStore:
    _by_id: dict[str, PhotoIntegrityFinding] = field(default_factory=dict)
    _pending_keys: dict[tuple[str, int, str], str] = field(default_factory=dict)

    @beartype
    def get_by_finding_id(self, finding_id: str) -> PhotoIntegrityFinding | None:
        return self._by_id.get(finding_id)

    @beartype
    def find_pending(
        self,
        *,
        batch_id: BatchId,
        photo_index: int,
        content_hash: str,
    ) -> PhotoIntegrityFinding | None:
        finding_id = self._pending_keys.get((batch_id.value, photo_index, content_hash))
        if finding_id is None:
            return None
        return self._by_id.get(finding_id)

    @beartype
    def save(self, finding: PhotoIntegrityFinding) -> None:
        self._by_id[finding.finding_id.value] = finding
        if finding.status == "pending_review":
            self._pending_keys[
                (finding.new_batch_id.value, finding.photo_index, finding.content_hash)
            ] = finding.finding_id.value

    @beartype
    def mark_alert_sent(self, finding_id: FindingId, sent_at: datetime) -> None:
        finding = self.get_by_finding_id(finding_id.value)
        if finding is None:
            return
        self.save(replace(finding, alert_sent_at=sent_at))
