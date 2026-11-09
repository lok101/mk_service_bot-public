from __future__ import annotations

import asyncio

from beartype import beartype

from src.config.settings import get_settings
from src.infrastructure.alerting import configure_ops_alert_logging
from src.infrastructure.alerting.worker_liveness_bootstrap import notify_bootstrap_failure
from src.infrastructure.composition import AppContainer, get_app_container


@beartype
async def main() -> None:
    try:
        settings = get_settings()
    except Exception as exc:
        notify_bootstrap_failure(entrypoint="run.py", error=exc)
        raise
    ops_logging = configure_ops_alert_logging(settings)
    container: AppContainer | None = None
    try:
        container = get_app_container()
        container.warm_up_reference_data()
        await container.run()
    finally:
        if container is not None:
            container.request_shutdown()
            await container.aclose_moysklad()
            container.close()
        if ops_logging is not None:
            ops_logging.stop()


if __name__ == "__main__":
    asyncio.run(main())
