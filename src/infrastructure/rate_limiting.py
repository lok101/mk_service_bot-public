from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum

from beartype import beartype


class KitShopApiPriority(Enum):
    """Класс доступа к бюджету Kit Shop HTTP: publish = high, sales/прочее = low."""

    HIGH = "high"
    LOW = "low"


class MoySkladApiPriority(Enum):
    """Класс доступа к Remap HTTP: document write = high, sync/catalog/prices = low."""

    HIGH = "high"
    LOW = "low"


_kitshop_api_priority: ContextVar[KitShopApiPriority] = ContextVar(
    "kitshop_api_priority",
    default=KitShopApiPriority.LOW,
)


@beartype
def current_kitshop_api_priority() -> KitShopApiPriority:
    return _kitshop_api_priority.get()


@beartype
@contextmanager
def kitshop_api_priority_scope(priority: KitShopApiPriority) -> Iterator[None]:
    """Явный high/low на весь вложенный HTTP path (Protocol sync_snapshot и т.п.)."""
    token = _kitshop_api_priority.set(priority)
    try:
        yield
    finally:
        _kitshop_api_priority.reset(token)


class SyncGlobalBackoff:
    """Глобальная блокировка при превышении лимита (429); все вызывающие ждут окончания backoff."""

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._blocked_until: float = 0.0

    @beartype
    def wait_if_blocked(self) -> None:
        while True:
            with self._lock:
                remaining = self._blocked_until - time.monotonic()
                if remaining <= 0:
                    return
            time.sleep(remaining)

    @beartype
    def trigger_backoff(self, timeout: float | None = None) -> None:
        duration = self._timeout if timeout is None else float(timeout)
        if duration <= 0:
            duration = self._timeout
        with self._lock:
            now = time.monotonic()
            if now < self._blocked_until:
                wait_until = self._blocked_until
            else:
                wait_until = now + duration
                self._blocked_until = wait_until

        remaining = wait_until - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    @beartype
    def is_blocked(self) -> bool:
        with self._lock:
            return time.monotonic() < self._blocked_until


class SyncInFlightLimiter:
    """Caps concurrent in-flight Remap HTTP for sync clients (1073 parallel limit)."""

    def __init__(self, max_in_flight: int) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        self.max_in_flight = max_in_flight
        self._sem = threading.BoundedSemaphore(max_in_flight)

    @beartype
    def acquire(self) -> None:
        self._sem.acquire()

    @beartype
    def release(self) -> None:
        self._sem.release()


class SyncRateLimiter:
    """Sync ограничитель запросов: max_requests за time_window секунд (sliding window)."""

    def __init__(self, max_requests: int, time_window: float = 1.0) -> None:
        self.max_requests = max_requests
        self.time_window = time_window
        self._requests: deque[float] = deque()
        self._lock = threading.Lock()

    @beartype
    def acquire(
        self,
        priority: KitShopApiPriority | MoySkladApiPriority | None = None,
        *,
        timeout: float | None = None,
    ) -> None:
        _ = priority  # Sheets/MoySklad plain window: priority ignored, FIFO
        wait_time = 0.0
        with self._lock:
            current_time = time.monotonic()

            while self._requests and self._requests[0] <= current_time - self.time_window:
                self._requests.popleft()

            if len(self._requests) < self.max_requests:
                self._requests.append(current_time)
                return

            wait_until = self._requests[0] + self.time_window
            wait_time = max(0.0, wait_until - current_time)
            if timeout is not None and wait_time > timeout:
                raise TimeoutError("rate limiter acquire timed out")
            self._requests.append(wait_until)
            self._requests.popleft()

        if wait_time > 0:
            time.sleep(wait_time)


class PrioritySyncRateLimiter:
    """Sync sliding-window лимитер с work-conserving bounded priority.

    Не более ``max_consecutive_high_requests`` выданных high подряд, если
    ожидает low; затем старейший low. Без ожидающего low high не простаивает.
    FIFO внутри каждого класса. По умолчанию — Kit Shop; для Remap передайте
    ``high``/``low`` = ``MoySkladApiPriority``.
    """

    def __init__(
        self,
        max_requests: int,
        time_window: float = 1.0,
        *,
        max_consecutive_high_requests: int = 3,
        high: KitShopApiPriority | MoySkladApiPriority = KitShopApiPriority.HIGH,
        low: KitShopApiPriority | MoySkladApiPriority = KitShopApiPriority.LOW,
    ) -> None:
        if max_consecutive_high_requests < 1:
            raise ValueError("max_consecutive_high_requests must be >= 1")
        self.max_requests = max_requests
        self.time_window = time_window
        self.max_consecutive_high_requests = max_consecutive_high_requests
        self._high = high
        self._low = low
        self._requests: deque[float] = deque()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._waiters: deque[tuple[KitShopApiPriority | MoySkladApiPriority, int]] = deque()
        self._next_ticket = 0
        self._high_streak = 0

    @beartype
    def acquire(
        self,
        priority: KitShopApiPriority | MoySkladApiPriority | None = None,
        *,
        timeout: float | None = None,
    ) -> None:
        effective: KitShopApiPriority | MoySkladApiPriority = (
            self._low if priority is None else priority
        )
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append((effective, ticket))
            self._cond.notify_all()

            while True:
                if not self._is_next_waiter(priority=effective, ticket=ticket):
                    if not self._wait_or_timeout(deadline):
                        self._remove_waiter(priority=effective, ticket=ticket)
                        self._cond.notify_all()
                        raise TimeoutError("rate limiter acquire timed out")
                    continue

                current_time = time.monotonic()
                while self._requests and self._requests[0] <= current_time - self.time_window:
                    self._requests.popleft()

                if len(self._requests) < self.max_requests:
                    self._requests.append(current_time)
                    self._remove_waiter(priority=effective, ticket=ticket)
                    self._record_grant(effective)
                    self._cond.notify_all()
                    return

                wait_until = self._requests[0] + self.time_window
                wait_time = max(0.0, wait_until - current_time)
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._remove_waiter(priority=effective, ticket=ticket)
                        self._cond.notify_all()
                        raise TimeoutError("rate limiter acquire timed out")
                    wait_time = min(wait_time, remaining) if wait_time > 0 else remaining
                self._cond.wait(timeout=wait_time if wait_time > 0 else 0.05)

    def _wait_or_timeout(self, deadline: float | None) -> bool:
        if deadline is None:
            self._cond.wait(timeout=0.05)
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        self._cond.wait(timeout=min(0.05, remaining))
        return deadline - time.monotonic() > 0

    def _record_grant(self, priority: KitShopApiPriority | MoySkladApiPriority) -> None:
        if priority is self._high:
            self._high_streak += 1
        else:
            self._high_streak = 0

    def _is_next_waiter(
        self,
        *,
        priority: KitShopApiPriority | MoySkladApiPriority,
        ticket: int,
    ) -> bool:
        if not self._waiters:
            return False
        highs = [item for item in self._waiters if item[0] is self._high]
        lows = [item for item in self._waiters if item[0] is self._low]
        if highs and not lows:
            return highs[0] == (priority, ticket)
        if lows and not highs:
            return lows[0] == (priority, ticket)
        if highs and lows and self._high_streak >= self.max_consecutive_high_requests:
            return lows[0] == (priority, ticket)
        if highs:
            return highs[0] == (priority, ticket)
        return lows[0] == (priority, ticket)

    def _remove_waiter(
        self,
        *,
        priority: KitShopApiPriority | MoySkladApiPriority,
        ticket: int,
    ) -> None:
        try:
            self._waiters.remove((priority, ticket))
        except ValueError:
            return


class AsyncGlobalBackoff:
    """Async глобальная блокировка при 429; все await'ящие ждут окончания backoff."""

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._blocked_until: float = 0.0

    @beartype
    async def wait_if_blocked(self) -> None:
        while True:
            async with self._lock:
                remaining = self._blocked_until - time.monotonic()
                if remaining <= 0:
                    return
            await asyncio.sleep(remaining)

    @beartype
    async def trigger_backoff(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._blocked_until:
                wait_until = self._blocked_until
            else:
                wait_until = now + self._timeout
                self._blocked_until = wait_until
        remaining = wait_until - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    @beartype
    async def is_blocked(self) -> bool:
        async with self._lock:
            return time.monotonic() < self._blocked_until


class AsyncRateLimiter:
    """Async ограничитель: max_requests за time_window (sliding window)."""

    def __init__(self, max_requests: int, time_window: float = 1.0) -> None:
        self.max_requests = max_requests
        self.time_window = time_window
        self._requests: deque[float] = deque()
        self._lock = asyncio.Lock()

    @beartype
    async def acquire(self, priority: MoySkladApiPriority | None = None) -> None:
        _ = priority  # plain window: priority ignored (FIFO)
        wait_time = 0.0
        async with self._lock:
            current_time = time.monotonic()
            while self._requests and self._requests[0] <= current_time - self.time_window:
                self._requests.popleft()
            if len(self._requests) < self.max_requests:
                self._requests.append(current_time)
                return
            wait_until = self._requests[0] + self.time_window
            wait_time = max(0.0, wait_until - current_time)
            self._requests.append(wait_until)
            self._requests.popleft()
        if wait_time > 0:
            await asyncio.sleep(wait_time)


class AsyncInFlightLimiter:
    """Async facade over ``SyncInFlightLimiter`` (shared process budget)."""

    def __init__(
        self,
        max_in_flight: int | None = None,
        *,
        shared: SyncInFlightLimiter | None = None,
    ) -> None:
        if shared is not None:
            self._sync = shared
        else:
            if max_in_flight is None or max_in_flight < 1:
                raise ValueError("max_in_flight must be >= 1")
            self._sync = SyncInFlightLimiter(max_in_flight)
        self.max_in_flight = self._sync.max_in_flight

    @beartype
    async def acquire(self) -> None:
        await asyncio.to_thread(self._sync.acquire)

    @beartype
    def release(self) -> None:
        self._sync.release()


class PriorityAsyncRateLimiter:
    """Async sliding-window Remap limiter with work-conserving bounded priority.

    Mirrors ``PrioritySyncRateLimiter``: at most ``max_consecutive_high_requests``
    high grants while a low waiter exists, then oldest low.
    """

    def __init__(
        self,
        max_requests: int,
        time_window: float = 1.0,
        *,
        max_consecutive_high_requests: int = 3,
    ) -> None:
        if max_consecutive_high_requests < 1:
            raise ValueError("max_consecutive_high_requests must be >= 1")
        self.max_requests = max_requests
        self.time_window = time_window
        self.max_consecutive_high_requests = max_consecutive_high_requests
        self._requests: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._waiters: deque[tuple[MoySkladApiPriority, int]] = deque()
        self._next_ticket = 0
        self._high_streak = 0
        self._wake = asyncio.Condition(self._lock)

    @beartype
    async def acquire(
        self,
        priority: MoySkladApiPriority | None = None,
    ) -> None:
        effective = MoySkladApiPriority.LOW if priority is None else priority
        async with self._wake:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append((effective, ticket))
            self._wake.notify_all()
            while True:
                if not self._is_next_waiter(priority=effective, ticket=ticket):
                    await self._wake.wait()
                    continue
                current_time = time.monotonic()
                while self._requests and self._requests[0] <= current_time - self.time_window:
                    self._requests.popleft()
                if len(self._requests) < self.max_requests:
                    self._requests.append(current_time)
                    self._remove_waiter(priority=effective, ticket=ticket)
                    self._record_grant(effective)
                    self._wake.notify_all()
                    return
                wait_until = self._requests[0] + self.time_window
                wait_time = max(0.0, wait_until - current_time)
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=max(wait_time, 0.05))
                except TimeoutError:
                    continue

    def _record_grant(self, priority: MoySkladApiPriority) -> None:
        if priority is MoySkladApiPriority.HIGH:
            self._high_streak += 1
        else:
            self._high_streak = 0

    def _is_next_waiter(self, *, priority: MoySkladApiPriority, ticket: int) -> bool:
        if not self._waiters:
            return False
        highs = [item for item in self._waiters if item[0] is MoySkladApiPriority.HIGH]
        lows = [item for item in self._waiters if item[0] is MoySkladApiPriority.LOW]
        if highs and not lows:
            return highs[0] == (priority, ticket)
        if lows and not highs:
            return lows[0] == (priority, ticket)
        if highs and lows and self._high_streak >= self.max_consecutive_high_requests:
            return lows[0] == (priority, ticket)
        if highs:
            return highs[0] == (priority, ticket)
        return lows[0] == (priority, ticket)

    def _remove_waiter(self, *, priority: MoySkladApiPriority, ticket: int) -> None:
        try:
            self._waiters.remove((priority, ticket))
        except ValueError:
            return
