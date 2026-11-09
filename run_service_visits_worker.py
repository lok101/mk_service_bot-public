from __future__ import annotations

import asyncio

from beartype import beartype

from src.config.settings import get_settings
from src.infrastructure.alerting import configure_ops_alert_logging
from src.infrastructure.alerting.worker_liveness_bootstrap import notify_bootstrap_failure
from src.infrastructure.composition.service_visits_worker_container import (
    ServiceVisitsWorkerContainer,
)


@beartype
async def main() -> None:
    try:
        settings = get_settings()
    except Exception as exc:
        notify_bootstrap_failure(entrypoint="run_service_visits_worker", error=exc)
        raise
    ops_logging = configure_ops_alert_logging(settings)
    container: ServiceVisitsWorkerContainer | None = None
    try:
        container = ServiceVisitsWorkerContainer.from_settings(settings)
        await container.run()
    finally:
        if container is not None:
            container.request_shutdown()
            container.close()
        if ops_logging is not None:
            ops_logging.stop()


if __name__ == "__main__":
    asyncio.run(main())
