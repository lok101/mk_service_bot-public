from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

import pytest
from tests.infrastructure.composition.test_assemble_app_container import (
    _dev_settings_without_mongo,
)
from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.outbox.handler_ids import (
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
)
from src.infrastructure.composition.effects_worker_container import EffectsWorkerContainer
from src.infrastructure.composition.runtime import (
    ProcessRuntime,
    run_no_sales_incident_poll,
)
from src.infrastructure.composition.wiring import wire_settlement as wire_settlement_mod
from src.infrastructure.composition.wiring.assemble import assemble_app_container
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


class _PollWorker:
    def __init__(self, *, raise_once: bool, shutdown: asyncio.Event) -> None:
        self.poll_interval_seconds = 0.01
        self.calls = 0
        self._raise_once = raise_once
        self._shutdown = shutdown

    async def process_batch_for_handler(self, handler_id: str, *, limit: int | None = None) -> int:
        del limit
        assert handler_id == NO_SALES_INCIDENT_CONTROL_HANDLER_ID
        self.calls += 1
        if self._raise_once and self.calls == 1:
            raise RuntimeError("poll failed")
        self._shutdown.set()
        return 1


def test_app_does_not_construct_kit_shop_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """error: ingress assemble never builds the Kit Shop HTTP client."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    calls: list[object] = []
    real = wire_settlement_mod.build_kitshop_client

    def _spy(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(wire_settlement_mod, "build_kitshop_client", _spy)
    container = assemble_app_container(_dev_settings_without_mongo())
    assert calls == []
    assert container.kitshop_client is None
    container.close()


def test_effects_assembles_kit_shop_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """happy: effects assemble is the process that builds the Kit Shop client."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    calls: list[object] = []
    real = wire_settlement_mod.build_kitshop_client

    def _spy(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(wire_settlement_mod, "build_kitshop_client", _spy)
    container = assemble_app_container(_dev_settings_without_mongo(), process="effects")
    assert len(calls) == 1
    container.close()


def test_narrow_poll_swallows_exception() -> None:
    """error: a failed no-sales poll iteration does not escape to the API task."""
    shutdown = asyncio.Event()
    worker = _PollWorker(raise_once=True, shutdown=shutdown)

    async def api_and_poll() -> None:
        api_done = asyncio.Event()

        async def api() -> None:
            await api_done.wait()

        async def poll() -> None:
            await run_no_sales_incident_poll(worker=worker, shutdown=shutdown)
            api_done.set()

        await asyncio.gather(api(), poll())

    asyncio.run(api_and_poll())
    assert worker.calls == 2


def test_narrow_poll_drains_after_enqueue_gap() -> None:
    """edge: the background poll claims a row left pending between enqueue and response."""
    shutdown = asyncio.Event()
    worker = _PollWorker(raise_once=False, shutdown=shutdown)

    async def once() -> None:
        async def stop_after_claim() -> None:
            while worker.calls == 0:
                await asyncio.sleep(0)
            shutdown.set()

        await asyncio.gather(
            run_no_sales_incident_poll(worker=worker, shutdown=shutdown),
            stop_after_claim(),
        )

    asyncio.run(once())
    assert worker.calls == 1


def test_ingress_tasks_skip_moved_polls() -> None:
    """happy: app background tasks are the watchdog and the narrow poll, not Kit ingest."""
    text_ingress = inspect.getsource(ProcessRuntime._ingress_background_tasks)
    text_effects = inspect.getsource(ProcessRuntime._effects_background_tasks)
    assert "_run_worker_liveness_watchdog_until_shutdown" in text_ingress
    assert "_run_sales_ingest_until_shutdown" not in text_ingress
    assert "_run_kitshop_sales_ingest_until_shutdown" not in text_ingress
    assert "_run_kitshop_reference_snapshot_until_shutdown" not in text_ingress
    assert "_run_sales_ingest_until_shutdown" in text_effects
    assert "_run_kitshop_sales_ingest_until_shutdown" in text_effects
    assert "_run_worker_liveness_watchdog_until_shutdown" not in text_effects


def test_effects_does_not_set_webhook_or_poll() -> None:
    """error: effects startup and run do not call set_webhook or Telegram polling."""
    for fn in (
        EffectsWorkerContainer.from_settings,
        EffectsWorkerContainer.run,
    ):
        text = inspect.getsource(fn)
        assert "set_webhook" not in text
        assert "configure_telegram_webhook" not in text
        assert "start_polling" not in text
    effects_run = inspect.getsource(EffectsWorkerContainer.run)
    assert "_effects_background_tasks" in effects_run
    app_run = inspect.getsource(ProcessRuntime.run)
    assert "configure_telegram_webhook" in app_run
    assert "run_until_shutdown" not in app_run


def test_photo_download_and_integrity_stay_together() -> None:
    """happy: both photo handlers are registered only on effects."""
    deps = _minimal_outbox_handler_deps(include_post_accountability=False)
    ingress = OutboxProcessorRegistry()
    effects = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=OutboxDomainEventPublisher(store=InMemoryOutboxStore()),
        processors=ingress,
        deps=deps,
        process="ingress",
    )
    register_outbox_handlers(
        publisher=OutboxDomainEventPublisher(store=InMemoryOutboxStore()),
        processors=effects,
        deps=replace(deps),
        process="effects",
    )
    assert not ingress.is_registered(LOADING_PHOTOS_HANDLER_ID)
    assert not ingress.is_registered(LOADING_PHOTOS_INTEGRITY_HANDLER_ID)
    assert effects.is_registered(LOADING_PHOTOS_HANDLER_ID)
    assert effects.is_registered(LOADING_PHOTOS_INTEGRITY_HANDLER_ID)
