from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class SyncPhotoBytesReader:
    """Sync adapter over async ``get_bytes`` for GroupClassifier."""

    get_bytes_async: Callable[[str], Awaitable[bytes]]

    @beartype
    def get_bytes(self, storage_key: str) -> bytes:
        async def _read() -> bytes:
            return await self.get_bytes_async(storage_key)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_read())
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _read()).result()
