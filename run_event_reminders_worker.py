from __future__ import annotations

import asyncio

from beartype import beartype

from src.config.settings import get_settings
from src.infrastructure.alerting import configure_ops_alert_logging
from src.infrastructure.composition.event_reminders_worker_container import (
    EventRemindersWorkerContainer,
)


@beartype
async def main() -> None:
    settings = get_settings()
    # Ops alert logging uses Telegram settings only (no Mongo).
    ops_logging = configure_ops_alert_logging(settings)
    container: EventRemindersWorkerContainer | None = None
    try:
        container = EventRemindersWorkerContainer.from_settings(settings)
        await container.run()
    finally:
        if container is not None:
            container.request_shutdown()
            container.close()
        if ops_logging is not None:
            ops_logging.stop()


if __name__ == "__main__":
    asyncio.run(main())
