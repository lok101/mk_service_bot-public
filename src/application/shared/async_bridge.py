from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine

from beartype import beartype

_thread_local = threading.local()
_main_event_loop: asyncio.AbstractEventLoop | None = None


@beartype
def bind_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the process main loop (e.g. uvicorn) for cross-thread MS calls."""
    global _main_event_loop
    _main_event_loop = loop


@beartype
def _has_running_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@beartype
def _run_on_thread_local_loop[T](coro: Coroutine[object, object, T]) -> T:
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _thread_local.loop = loop
    return loop.run_until_complete(coro)


@beartype
def run_coroutine_sync[T](coro: Coroutine[object, object, T]) -> T:
    """Run an async coroutine from synchronous code.

    When the main event loop is running (FastAPI worker thread pool), schedules
    the coroutine on that loop so shared ``httpx.AsyncClient`` stays valid.
    Otherwise keeps a per-thread event loop alive (tests, CLI).
    """
    if _has_running_event_loop():
        msg = "run_coroutine_sync cannot be called from a running event loop"
        raise RuntimeError(msg)
    main = _main_event_loop
    if main is not None and main.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, main)
        return future.result()
    return _run_on_thread_local_loop(coro)
