from __future__ import annotations

from datetime import date

from src.application.service_visits.visit_ids import (
    ad_hoc_visit_id,
    is_day_based_no_sales_visit_id,
    no_sales_incident_visit_id,
    offline_incident_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import EventId, MachineId

_MACHINE = MachineId("101")


def test_scheduled_visit_id_format() -> None:
    assert scheduled_visit_id(_MACHINE, date(2026, 8, 11)) == "scheduled:101:2026-08-11"


def test_offline_incident_visit_id_format() -> None:
    assert offline_incident_visit_id(EventId("evt-off-1")) == "incident:offline:evt-off-1"


def test_no_sales_incident_visit_id_sticky_format() -> None:
    """happy: без report_day."""
    assert no_sales_incident_visit_id(_MACHINE) == "incident:no_sales:101"


def test_is_day_based_no_sales_visit_id() -> None:
    """edge: legacy day id vs sticky."""
    assert is_day_based_no_sales_visit_id("incident:no_sales:101:2026-08-10") is True
    assert is_day_based_no_sales_visit_id("incident:no_sales:101") is False


def test_ad_hoc_visit_id_format() -> None:
    assert (
        ad_hoc_visit_id(_MACHINE, date(2026, 8, 12), EventId("mnt-1"))
        == "ad_hoc:101:2026-08-12:mnt-1"
    )
