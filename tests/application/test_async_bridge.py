from __future__ import annotations

import asyncio
import threading

import httpx

from src.application.shared.async_bridge import bind_main_event_loop, run_coroutine_sync


def test_run_coroutine_sync_reuses_loop_for_shared_async_client() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        _ = request
        calls += 1
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )

    async def fetch() -> dict[str, object]:
        response = await client.get("/")
        return response.json()

    assert run_coroutine_sync(fetch()) == {"ok": True}
    assert run_coroutine_sync(fetch()) == {"ok": True}
    assert calls == 2

    run_coroutine_sync(client.aclose())


def test_run_coroutine_sync_from_worker_thread_uses_main_loop() -> None:
    loop = asyncio.new_event_loop()
    bind_main_event_loop(loop)

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=loop_thread, daemon=True)
    thread.start()

    async def work() -> int:
        await asyncio.sleep(0)
        return 42

    try:
        assert run_coroutine_sync(work()) == 42
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
