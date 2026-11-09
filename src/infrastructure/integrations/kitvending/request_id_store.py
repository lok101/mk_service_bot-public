from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable

from beartype import beartype


@runtime_checkable
class KitVendingRequestIdStore(Protocol):
    @beartype
    def next_id(self, *, login: str) -> int: ...

    @beartype
    def bump_floor(self, *, login: str, floor: int) -> None: ...


@beartype
class InMemoryKitVendingRequestIdStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watermarks: dict[str, int] = {}

    @beartype
    def next_id(self, *, login: str) -> int:
        with self._lock:
            floor_ms = int(time.time() * 1000)
            stored = self._watermarks.get(login, 0)
            candidate = max(stored + 1, floor_ms)
            self._watermarks[login] = candidate
            return candidate

    @beartype
    def bump_floor(self, *, login: str, floor: int) -> None:
        with self._lock:
            stored = self._watermarks.get(login, 0)
            self._watermarks[login] = max(stored, floor)
