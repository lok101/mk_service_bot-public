from __future__ import annotations

from src.application.outbox.handler_ids import SERVICE_VISIT_INCIDENT_HANDLER_ID
from src.application.sales_monitoring.run_offline_poll import (
    SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS,
)


def test_sales_monitoring_worker_drains_service_visit_incident() -> None:
    assert SERVICE_VISIT_INCIDENT_HANDLER_ID in SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS
