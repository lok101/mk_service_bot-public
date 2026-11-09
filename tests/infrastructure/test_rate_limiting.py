from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
    KitShopApiPriority,
    MoySkladApiPriority,
    PriorityAsyncRateLimiter,
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncRateLimiter,
)


def test_rate_limiter_blocks_second_call_within_window() -> None:
    # happy
    limiter = SyncRateLimiter(max_requests=1, time_window=0.05)
    limiter.acquire()
    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04


def test_global_backoff_blocks_until_timeout() -> None:
    # happy
    backoff = SyncGlobalBackoff(timeout=0.05)
    start = time.monotonic()
    backoff.trigger_backoff()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04
    assert backoff.is_blocked() is False


def test_global_backoff_second_trigger_waits_existing() -> None:
    # edge: второй trigger_backoff во время активной блокировки ждёт исходный дедлайн
    backoff = SyncGlobalBackoff(timeout=0.05)
    blocker = threading.Thread(target=backoff.trigger_backoff)
    blocker.start()
    time.sleep(0.01)
    assert backoff.is_blocked() is True
    backoff.trigger_backoff()
    blocker.join()
    assert backoff.is_blocked() is False


def test_rate_limiter_allows_two_requests_within_window_when_max_is_two() -> None:
    # happy: max_requests=2 не блокирует второй быстрый запрос
    limiter = SyncRateLimiter(max_requests=2, time_window=0.2)
    start = time.monotonic()
    limiter.acquire()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


def test_async_rate_limiter_blocks_second_call_within_window() -> None:
    # happy
    async def run() -> float:
        limiter = AsyncRateLimiter(max_requests=1, time_window=0.05)
        await limiter.acquire()
        start = asyncio.get_running_loop().time()
        await limiter.acquire()
        return asyncio.get_running_loop().time() - start

    elapsed = asyncio.run(run())
    assert elapsed >= 0.04


def test_async_rate_limiter_allows_two_when_max_is_two() -> None:
    # happy
    async def run() -> float:
        limiter = AsyncRateLimiter(max_requests=2, time_window=0.2)
        start = asyncio.get_running_loop().time()
        await limiter.acquire()
        await limiter.acquire()
        return asyncio.get_running_loop().time() - start

    assert asyncio.run(run()) < 0.05


def test_async_global_backoff_blocks_until_timeout() -> None:
    # happy
    async def run() -> tuple[float, bool]:
        backoff = AsyncGlobalBackoff(timeout=0.05)
        start = asyncio.get_running_loop().time()
        await backoff.trigger_backoff()
        elapsed = asyncio.get_running_loop().time() - start
        blocked_after = await backoff.is_blocked()
        return elapsed, blocked_after

    elapsed, blocked_after = asyncio.run(run())
    assert elapsed >= 0.04
    assert blocked_after is False


def test_async_global_backoff_wait_if_blocked_while_other_holds() -> None:
    # edge: wait_if_blocked ждёт, пока активен blocked_until от параллельного trigger
    async def run() -> None:
        backoff = AsyncGlobalBackoff(timeout=0.1)
        waiter_done = asyncio.Event()

        async def trigger() -> None:
            await backoff.trigger_backoff()

        async def waiter() -> None:
            await asyncio.sleep(0.01)
            await backoff.wait_if_blocked()
            waiter_done.set()

        await asyncio.gather(trigger(), waiter())
        assert waiter_done.is_set()
        assert await backoff.is_blocked() is False

    asyncio.run(run())


def test_async_rate_limiter_uses_asyncio_sleep() -> None:
    # error/invariant: acquire при полном окне зовёт asyncio.sleep, не time.sleep
    sleep = AsyncMock()

    async def run() -> None:
        limiter = AsyncRateLimiter(max_requests=1, time_window=1.0)
        await limiter.acquire()
        with patch("src.infrastructure.rate_limiting.asyncio.sleep", sleep):
            await limiter.acquire()

    asyncio.run(run())
    sleep.assert_awaited()


def test_priority_waiting_high_gets_next_slot_before_low() -> None:
    # happy: полное окно + ждущий high получает следующий слот раньше low.
    # Окно 2 с, чтобы под coverage слот не открылся раньше, чем high встанет в очередь.
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=2.0)
    limiter.acquire(priority=KitShopApiPriority.LOW)

    order: list[str] = []
    started = threading.Barrier(3)

    def run_low() -> None:
        started.wait()
        limiter.acquire(priority=KitShopApiPriority.LOW)
        order.append("low")

    def run_high() -> None:
        started.wait()
        time.sleep(0.05)
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append("high")

    low_thread = threading.Thread(target=run_low)
    high_thread = threading.Thread(target=run_high)
    low_thread.start()
    high_thread.start()
    started.wait()
    low_thread.join(timeout=8.0)
    high_thread.join(timeout=8.0)
    assert order == ["high", "low"]


def test_priority_low_starts_after_high_releases() -> None:
    # happy: после ухода high — low получает слот
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=0.05)
    limiter.acquire(priority=KitShopApiPriority.HIGH)
    start = time.monotonic()
    limiter.acquire(priority=KitShopApiPriority.LOW)
    assert time.monotonic() - start >= 0.04


def test_priority_multiple_high_are_fifo() -> None:
    # edge: несколько high — FIFO среди high
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=0.15)
    limiter.acquire(priority=KitShopApiPriority.HIGH)

    order: list[int] = []
    first_registered = threading.Event()
    started = threading.Barrier(3)

    def run_high(seq: int, *, wait_for_first: bool) -> None:
        started.wait()
        if wait_for_first:
            first_registered.wait(timeout=2.0)
            time.sleep(0.02)
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append(seq)

    def run_first() -> None:
        started.wait()
        first_registered.set()
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append(1)

    t1 = threading.Thread(target=run_first)
    t2 = threading.Thread(target=run_high, args=(2,), kwargs={"wait_for_first": True})
    t1.start()
    t2.start()
    started.wait()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert order == [1, 2]


def test_priority_low_without_high_keeps_window_spacing() -> None:
    # edge: low без concurrent high — прежний spacing окна
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=0.05)
    limiter.acquire(priority=KitShopApiPriority.LOW)
    start = time.monotonic()
    limiter.acquire(priority=KitShopApiPriority.LOW)
    assert time.monotonic() - start >= 0.04


def test_priority_default_acquire_is_low() -> None:
    # edge: default без явного priority = low (не обгоняет high)
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=0.2)
    limiter.acquire()

    order: list[str] = []
    started = threading.Barrier(3)

    def run_default() -> None:
        started.wait()
        limiter.acquire()
        order.append("default")

    def run_high() -> None:
        started.wait()
        time.sleep(0.05)
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append("high")

    default_thread = threading.Thread(target=run_default)
    high_thread = threading.Thread(target=run_high)
    default_thread.start()
    high_thread.start()
    started.wait()
    default_thread.join(timeout=3.0)
    high_thread.join(timeout=3.0)
    assert order == ["high", "default"]


def test_sync_rate_limiter_acquire_ignores_priority_kwarg() -> None:
    # edge: Sheets/MoySklad SyncRateLimiter остаётся default-совместимым
    limiter = SyncRateLimiter(max_requests=2, time_window=0.2)
    limiter.acquire(priority=KitShopApiPriority.HIGH)
    limiter.acquire()


def test_priority_acquire_timeout_removes_waiter() -> None:
    # edge: UI low не остаётся в очереди навечно за high publish
    limiter = PrioritySyncRateLimiter(max_requests=1, time_window=1.0)
    limiter.acquire(priority=KitShopApiPriority.HIGH)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="rate limiter"):
        limiter.acquire(priority=KitShopApiPriority.LOW, timeout=0.15)
    assert time.monotonic() - started < 0.5
    # waiter снят — следующий high не блокируется брошенным low
    started_high = time.monotonic()
    # слот ещё занят окном; ждём освобождения без чужого low впереди
    limiter.acquire(priority=KitShopApiPriority.HIGH, timeout=1.5)
    assert time.monotonic() - started_high < 1.6


def test_priority_high_streak_then_waiting_low() -> None:
    # happy: после трёх high старейший ожидающий low получает слот
    limiter = PrioritySyncRateLimiter(
        max_requests=1,
        time_window=0.08,
        max_consecutive_high_requests=3,
    )
    limiter.acquire(priority=KitShopApiPriority.LOW)  # occupy window; streak stays 0
    order: list[str] = []
    h1_in = threading.Event()
    h2_in = threading.Event()
    h3_in = threading.Event()
    low_in = threading.Event()

    def run(label: str, priority: KitShopApiPriority, entered: threading.Event) -> None:
        entered.set()
        limiter.acquire(priority=priority)
        order.append(label)

    threads = [
        threading.Thread(target=run, args=("h1", KitShopApiPriority.HIGH, h1_in)),
        threading.Thread(target=run, args=("h2", KitShopApiPriority.HIGH, h2_in)),
        threading.Thread(target=run, args=("h3", KitShopApiPriority.HIGH, h3_in)),
        threading.Thread(target=run, args=("low", KitShopApiPriority.LOW, low_in)),
    ]
    threads[0].start()
    assert h1_in.wait(timeout=1.0)
    time.sleep(0.02)
    threads[1].start()
    assert h2_in.wait(timeout=1.0)
    time.sleep(0.02)
    threads[2].start()
    assert h3_in.wait(timeout=1.0)
    time.sleep(0.02)
    threads[3].start()
    assert low_in.wait(timeout=1.0)
    for thread in threads:
        thread.join(timeout=5.0)
    assert order == ["h1", "h2", "h3", "low"]


def test_priority_all_high_when_no_low_waiting() -> None:
    # edge: без low все слоты high (work-conserving)
    limiter = PrioritySyncRateLimiter(
        max_requests=1,
        time_window=0.08,
        max_consecutive_high_requests=3,
    )
    limiter.acquire(priority=KitShopApiPriority.HIGH)
    order: list[int] = []
    prev = threading.Event()
    prev.set()

    def run(seq: int, gate: threading.Event, entered: threading.Event) -> None:
        gate.wait(timeout=2.0)
        time.sleep(0.02)
        entered.set()
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append(seq)

    events = [threading.Event() for _ in range(4)]
    threads = []
    gate = threading.Event()
    gate.set()
    for i in range(4):
        entered = events[i]
        threads.append(
            threading.Thread(target=run, args=(i + 1, gate if i == 0 else events[i - 1], entered))
        )
    for thread in threads:
        thread.start()
        time.sleep(0.01)
    for thread in threads:
        thread.join(timeout=5.0)
    assert order == [1, 2, 3, 4]


def test_priority_fifo_within_class_after_streak() -> None:
    # edge: после streak два low — FIFO внутри low
    limiter = PrioritySyncRateLimiter(
        max_requests=1,
        time_window=0.08,
        max_consecutive_high_requests=1,
    )
    limiter.acquire(priority=KitShopApiPriority.HIGH)  # streak = 1
    order: list[str] = []
    first_low_registered = threading.Event()

    def run_low1() -> None:
        first_low_registered.set()
        limiter.acquire(priority=KitShopApiPriority.LOW)
        order.append("low1")

    def run_low2() -> None:
        first_low_registered.wait(timeout=2.0)
        time.sleep(0.02)
        limiter.acquire(priority=KitShopApiPriority.LOW)
        order.append("low2")

    t1 = threading.Thread(target=run_low1)
    t2 = threading.Thread(target=run_low2)
    t1.start()
    assert first_low_registered.wait(timeout=1.0)
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert order == ["low1", "low2"]


def test_priority_timeout_removes_waiter_without_grant() -> None:
    # edge: timeout low не меняет streak — low после max streak всё ещё обгоняет high
    limiter = PrioritySyncRateLimiter(
        max_requests=1,
        time_window=1.0,
        max_consecutive_high_requests=1,
    )
    limiter.acquire(priority=KitShopApiPriority.HIGH)
    with pytest.raises(TimeoutError, match="rate limiter"):
        limiter.acquire(priority=KitShopApiPriority.LOW, timeout=0.1)
    order: list[str] = []
    low_in = threading.Event()

    def run_low() -> None:
        low_in.set()
        limiter.acquire(priority=KitShopApiPriority.LOW)
        order.append("low")

    def run_high() -> None:
        low_in.wait(timeout=2.0)
        time.sleep(0.02)
        limiter.acquire(priority=KitShopApiPriority.HIGH)
        order.append("high")

    low_t = threading.Thread(target=run_low)
    high_t = threading.Thread(target=run_high)
    low_t.start()
    assert low_in.wait(timeout=1.0)
    high_t.start()
    low_t.join(timeout=3.0)
    high_t.join(timeout=3.0)
    assert order == ["low", "high"]


def test_priority_rejects_max_consecutive_high_below_one() -> None:
    # error
    with pytest.raises(ValueError, match="max_consecutive_high_requests"):
        PrioritySyncRateLimiter(max_requests=1, time_window=1.0, max_consecutive_high_requests=0)


def test_async_in_flight_caps_parallel_acquires() -> None:
    # happy: max_in_flight=1 serializes overlapping holders
    limiter = AsyncInFlightLimiter(max_in_flight=1)
    peak = {"value": 0}
    current = {"value": 0}

    async def worker() -> None:
        await limiter.acquire()
        try:
            current["value"] += 1
            peak["value"] = max(peak["value"], current["value"])
            await asyncio.sleep(0.05)
            current["value"] -= 1
        finally:
            limiter.release()

    async def run() -> None:
        await asyncio.gather(worker(), worker())

    asyncio.run(run())
    assert peak["value"] == 1


def test_async_in_flight_rejects_zero() -> None:
    # error
    with pytest.raises(ValueError, match="max_in_flight"):
        AsyncInFlightLimiter(max_in_flight=0)


def test_async_and_sync_in_flight_share_budget() -> None:
    # happy: one SyncInFlightLimiter shared with AsyncInFlightLimiter → peak 1
    from src.infrastructure.rate_limiting import SyncInFlightLimiter

    sync = SyncInFlightLimiter(max_in_flight=1)
    async_lim = AsyncInFlightLimiter(shared=sync)
    peak = {"value": 0}
    current = {"value": 0}
    hold = threading.Event()
    sync_held = threading.Event()

    def sync_worker() -> None:
        sync.acquire()
        try:
            current["value"] += 1
            peak["value"] = max(peak["value"], current["value"])
            sync_held.set()
            hold.wait(timeout=2.0)
            current["value"] -= 1
        finally:
            sync.release()

    async def async_worker() -> None:
        await async_lim.acquire()
        try:
            current["value"] += 1
            peak["value"] = max(peak["value"], current["value"])
            await asyncio.sleep(0.05)
            current["value"] -= 1
        finally:
            async_lim.release()

    async def run() -> None:
        t = threading.Thread(target=sync_worker)
        t.start()
        assert sync_held.wait(timeout=2.0)
        task = asyncio.create_task(async_worker())
        await asyncio.sleep(0.05)
        hold.set()
        await task
        t.join(timeout=2.0)

    asyncio.run(run())
    assert peak["value"] == 1


def test_priority_async_high_streak_then_waiting_low() -> None:
    # happy: after N high, waiting low gets the next grant
    limiter = PriorityAsyncRateLimiter(
        max_requests=1,
        time_window=0.08,
        max_consecutive_high_requests=3,
    )
    order: list[str] = []

    async def occupy() -> None:
        await limiter.acquire(priority=MoySkladApiPriority.LOW)

    async def run(label: str, priority: MoySkladApiPriority) -> None:
        await limiter.acquire(priority=priority)
        order.append(label)

    async def scenario() -> None:
        await occupy()
        await asyncio.gather(
            run("h1", MoySkladApiPriority.HIGH),
            run("h2", MoySkladApiPriority.HIGH),
            run("h3", MoySkladApiPriority.HIGH),
            run("low", MoySkladApiPriority.LOW),
        )

    asyncio.run(scenario())
    assert order == ["h1", "h2", "h3", "low"]


def test_priority_async_rejects_max_consecutive_high_below_one() -> None:
    # error
    with pytest.raises(ValueError, match="max_consecutive_high_requests"):
        PriorityAsyncRateLimiter(
            max_requests=1,
            time_window=1.0,
            max_consecutive_high_requests=0,
        )
