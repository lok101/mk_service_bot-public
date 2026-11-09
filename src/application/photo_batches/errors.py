from __future__ import annotations

from beartype import beartype


class PhotoBatchRejectedError(Exception):
    @beartype
    def __init__(self, reason: str) -> None:
        if not reason:
            raise ValueError("rejection reason must not be empty")
        self.reason = reason
        super().__init__(reason)
