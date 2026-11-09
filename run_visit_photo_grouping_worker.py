from __future__ import annotations

import asyncio

from beartype import beartype

from src.config.settings import get_settings
from src.infrastructure.alerting import configure_ops_alert_logging
from src.infrastructure.composition.visit_photo_grouping_worker_container import (
    VisitPhotoGroupingWorkerContainer,
)


@beartype
async def main() -> None:
    settings = get_settings()
    ops_logging = configure_ops_alert_logging(settings)
    container: VisitPhotoGroupingWorkerContainer | None = None
    try:
        container = VisitPhotoGroupingWorkerContainer.from_settings(settings)
        await container.run()
    finally:
        if container is not None:
            container.request_shutdown()
            container.close()
        if ops_logging is not None:
            ops_logging.stop()


if __name__ == "__main__":
    asyncio.run(main())
