from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from aiogram import Bot
from beartype import beartype

from src.config.settings import Settings, get_settings
from src.infrastructure.composition.container import AppContainer
from src.infrastructure.composition.effects_worker_heartbeat import (
    EffectsWorkerStatusCollection,
    effects_worker_heartbeat_loop,
)
from src.infrastructure.composition.wiring.assemble import assemble_app_container
from src.infrastructure.mongodb.connection import resolve_collection

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass
class EffectsWorkerContainer:
    """Outbox drain for moved handlers. Does not serve HTTP and does not set a webhook."""

    app: AppContainer
    bot: Bot
    _shutdown: asyncio.Event = field(default_factory=asyncio.Event)

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> EffectsWorkerContainer:
        app = assemble_app_container(settings, process="effects")
        bot, _dispatcher = app.setup_telegram_bot(process="effects")
        handler_ids = ",".join(sorted(app.outbox.processors.registered_handler_ids()))
        _LOGGER.info("effects_worker_handlers %s", handler_ids)
        return cls(app=app, bot=bot)

    @beartype
    def _status_collection(self) -> EffectsWorkerStatusCollection | None:
        settings = get_settings()
        client = self.app._runtime.persistence.mongo_client
        if client is None or not settings.mongodb.is_configured:
            return None
        return resolve_collection(
            settings.mongodb,
            collection_name=settings.effects_worker.status_collection,
            owner="EffectsWorkerContainer",
            client=client,
        )

    @beartype
    async def run(self) -> None:
        runtime = self.app._runtime
        tasks = runtime._effects_background_tasks()
        try:
            await asyncio.gather(
                runtime.outbox.worker.run_until_shutdown(runtime._shutdown_event),
                effects_worker_heartbeat_loop(
                    self._status_collection(),
                    runtime._shutdown_event,
                ),
                *tasks,
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            runtime._close_kitvending_client()

    @beartype
    def request_shutdown(self) -> None:
        self._shutdown.set()
        self.app._runtime.request_shutdown()

    @beartype
    def close(self) -> None:
        self.app.close()
