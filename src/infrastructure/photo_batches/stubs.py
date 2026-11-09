from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.photo_batches.ports import DownloadedPhoto
from src.domain.ids import BatchId


@beartype
@dataclass
class StubTelegramPhotoDownloader:
    content_type: str = "image/jpeg"
    payload: bytes = b"stub-photo-bytes"

    @beartype
    async def download(self, file_id: str) -> DownloadedPhoto:
        if not file_id:
            raise ValueError("file_id must not be empty")
        return DownloadedPhoto(
            data=self.payload,
            content_type=self.content_type,
        )


@beartype
@dataclass
class InMemoryPhotoStorage:
    _objects: dict[str, bytes] = field(default_factory=dict)

    @beartype
    async def save(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
    ) -> str:
        if not content_type:
            raise ValueError("content_type must not be empty")
        storage_key = f"memory://{batch_id.value}/{index}"
        self._objects[storage_key] = data
        return storage_key

    @beartype
    async def get_bytes(self, storage_key: str) -> bytes:
        try:
            return self._objects[storage_key]
        except KeyError as error:
            raise ValueError(f"Unknown storage key: {storage_key!r}") from error

    @beartype
    async def delete(self, storage_key: str) -> None:
        self._objects.pop(storage_key, None)
