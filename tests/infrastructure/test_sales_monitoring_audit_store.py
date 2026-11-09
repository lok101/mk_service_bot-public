from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

import mongomock

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.mongodb.sales_monitoring_audit import MongoSalesMonitoringAuditStore
from src.infrastructure.mongodb.sales_monitoring_audit_documents import (
    no_sales_audit_document_id,
    no_sales_episode_document_id,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE_ID = MachineId("vm-audit-01")
_NO_SALES_MACHINE_ID = MachineId("101")
_REPORT_DAY = date(2026, 7, 28)
_OCCURRED = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
_CLEARED_AT = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)
_LAST_SALE_AT = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)


def _yesterday_no_sales() -> SalesMonitoringYesterdayNoSales:
    return SalesMonitoringYesterdayNoSales(
        event_id=EventId(
            f"SalesMonitoringYesterdayNoSales:{_MACHINE_ID.value}:{_REPORT_DAY.isoformat()}"
        ),
        machine_id=_MACHINE_ID,
        report_day=_REPORT_DAY,
        occurred_at=_OCCURRED,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _offline_opened() -> SalesMonitoringOfflineOpened:
    return SalesMonitoringOfflineOpened(
        event_id=EventId(
            f"sales-monitoring-offline-opened:{_MACHINE_ID.value}:{_OPENED_AT.isoformat()}"
        ),
        machine_id=_MACHINE_ID,
        opened_at=_OPENED_AT,
        occurred_at=_OPENED_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _offline_cleared() -> SalesMonitoringOfflineCleared:
    opened = _offline_opened()
    return SalesMonitoringOfflineCleared(
        event_id=EventId(
            f"sales-monitoring-offline-cleared:{_MACHINE_ID.value}:{_CLEARED_AT.isoformat()}"
        ),
        machine_id=_MACHINE_ID,
        opened_event_id=opened.event_id,
        opened_at=_OPENED_AT,
        cleared_at=_CLEARED_AT,
        occurred_at=_CLEARED_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def test_sales_audit_id_format() -> None:
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    event = _yesterday_no_sales()

    store.upsert_from_event(event)

    expected_id = f"SalesMonitoringYesterdayNoSales:{_MACHINE_ID.value}:{_REPORT_DAY.isoformat()}"
    document = collection.find_one({"_id": expected_id})
    assert document is not None
    assert document["_id"] == expected_id
    assert document["machine_id"] == _MACHINE_ID.value
    assert document["report_day"] == _REPORT_DAY.isoformat()


def test_offline_audit_upsert_open_then_cleared() -> None:
    store = InMemorySalesMonitoringAuditStore()
    opened = _offline_opened()
    cleared = _offline_cleared()

    store.upsert_from_event(opened)
    open_docs = store.list_open_offline()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == f"offline:{_MACHINE_ID.value}"
    assert open_docs[0]["status"] == "open"
    assert open_docs[0]["opened_at"] == _OPENED_AT

    store.upsert_from_event(cleared)
    assert store.list_open_offline() == []
    document = store.get(f"offline:{_MACHINE_ID.value}")
    assert document is not None
    assert document["_id"] == f"offline:{_MACHINE_ID.value}"
    assert document["status"] == "cleared"
    assert document["opened_at"] == _OPENED_AT
    assert document["cleared_at"] == _CLEARED_AT


def test_mongo_offline_audit_upsert_open_then_cleared() -> None:
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _offline_opened()
    cleared = _offline_cleared()

    store.upsert_from_event(opened)
    open_docs = store.list_open_offline()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == f"offline:{_MACHINE_ID.value}"
    assert open_docs[0]["status"] == "open"
    assert open_docs[0]["opened_at"] == _OPENED_AT

    store.upsert_from_event(cleared)
    assert store.list_open_offline() == []
    document = store.get(f"offline:{_MACHINE_ID.value}")
    assert document is not None
    assert document["_id"] == f"offline:{_MACHINE_ID.value}"
    assert document["status"] == "cleared"
    assert document["opened_at"] == _OPENED_AT
    assert document["cleared_at"] == _CLEARED_AT


def _no_sales_stale_opened() -> SalesMonitoringNoSalesStaleOpened:
    return SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{_OPENED_AT.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=_OPENED_AT,
        occurred_at=_OPENED_AT,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _no_sales_stale_cleared(
    *,
    clear_trigger: Literal["sale", "exclude"] | None = None,
    bypass_active: bool | None = None,
    cleared_at: datetime | None = None,
    opened_event_id: EventId | None = None,
    last_sale_at: datetime | None = _LAST_SALE_AT,
    machine_id: MachineId | None = None,
    opened_at: datetime | None = None,
) -> SalesMonitoringNoSalesStaleCleared:
    opened = _no_sales_stale_opened()
    machine = machine_id if machine_id is not None else _NO_SALES_MACHINE_ID
    cleared_moment = cleared_at if cleared_at is not None else _CLEARED_AT
    opened_moment = opened_at if opened_at is not None else _OPENED_AT
    opened_id = opened_event_id if opened_event_id is not None else opened.event_id
    return SalesMonitoringNoSalesStaleCleared(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-cleared:{machine.value}:{cleared_moment.isoformat()}"
        ),
        machine_id=machine,
        opened_event_id=opened_id,
        opened_at=opened_moment,
        cleared_at=cleared_moment,
        occurred_at=cleared_moment,
        last_sale_at=last_sale_at,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
        clear_trigger=clear_trigger,
        bypass_active=bypass_active,
    )


def test_no_sales_stale_audit_upsert_open_then_cleared() -> None:
    """happy: sticky _id no_sales:{machine}; open затем cleared."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared()

    store.upsert_from_event(opened)
    document = store.get(f"no_sales:{_NO_SALES_MACHINE_ID.value}")
    assert document is not None
    assert document["_id"] == "no_sales:101"
    assert document["kind"] == "no_sales"
    assert document["status"] == "open"
    assert document["opened_at"] == _OPENED_AT
    assert document["cleared_at"] is None
    assert document["last_sale_at"] == _LAST_SALE_AT
    assert document["opened_event_id"] == opened.event_id.value

    store.upsert_from_event(cleared)
    document = store.get(f"no_sales:{_NO_SALES_MACHINE_ID.value}")
    assert document is not None
    assert document["_id"] == "no_sales:101"
    assert document["status"] == "cleared"
    assert document["opened_at"] == _OPENED_AT
    assert document["cleared_at"] == _CLEARED_AT
    assert document["last_sale_at"] == _LAST_SALE_AT


def test_list_open_no_sales_returns_only_open() -> None:
    """edge: cleared не в list_open_no_sales."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared()

    store.upsert_from_event(opened)
    open_docs = store.list_open_no_sales()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == "no_sales:101"
    assert open_docs[0]["status"] == "open"

    store.upsert_from_event(cleared)
    assert store.list_open_no_sales() == []


def test_list_cleared_no_sales_since_filters_by_cleared_at() -> None:
    """happy: только cleared с cleared_at >= since; open не входит."""
    store = InMemorySalesMonitoringAuditStore()
    store.upsert_from_event(_no_sales_stale_opened())
    store.upsert_from_event(_no_sales_stale_cleared())

    since = _CLEARED_AT
    docs = store.list_cleared_no_sales_since(cleared_at_gte=since)
    assert len(docs) == 1
    assert docs[0]["machine_id"] == _NO_SALES_MACHINE_ID.value
    assert docs[0]["status"] == "cleared"

    too_late = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)
    assert store.list_cleared_no_sales_since(cleared_at_gte=too_late) == []


def test_list_cleared_no_sales_since_excludes_open() -> None:
    """edge: open sticky не в cleared list."""
    store = InMemorySalesMonitoringAuditStore()
    store.upsert_from_event(_no_sales_stale_opened())
    assert store.list_cleared_no_sales_since(cleared_at_gte=_OPENED_AT) == []


def test_mongo_list_cleared_no_sales_since() -> None:
    """happy: Mongo find parity с memory."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    store.upsert_from_event(_no_sales_stale_opened())
    store.upsert_from_event(_no_sales_stale_cleared())
    docs = store.list_cleared_no_sales_since(cleared_at_gte=_CLEARED_AT)
    assert len(docs) == 1
    assert docs[0]["status"] == "cleared"
    assert docs[0]["cleared_at"] == _CLEARED_AT


def test_opened_upserts_sticky_and_open_episode() -> None:
    """happy: Opened пишет sticky open и episode с cleared_at/trigger/bypass = None."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()

    store.upsert_from_event(opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert sticky is not None and sticky["status"] == "open"
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["opened_event_id"] == opened.event_id.value
    assert episode["cleared_at"] is None
    assert episode["clear_trigger"] is None
    assert episode["bypass_active"] is None
    assert "clearance_outcome" not in episode


def test_second_open_keeps_first_episode_and_creates_second() -> None:
    """edge: второе Opened сохраняет первый episode и создаёт второй open-episode."""
    store = InMemorySalesMonitoringAuditStore()
    first_opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(first_opened)
    store.upsert_from_event(cleared)

    first_episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, first_opened.event_id)
    first_episode = store.get(first_episode_id)
    assert first_episode is not None
    assert first_episode["clear_trigger"] == "sale"
    assert first_episode["cleared_at"] == _CLEARED_AT

    second_opened_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    second_opened = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{second_opened_at.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=second_opened_at,
        occurred_at=second_opened_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-2"),
        assigned_technician_display="Пётр",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    store.upsert_from_event(second_opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "open"
    assert sticky["opened_event_id"] == second_opened.event_id.value

    kept_first = store.get(first_episode_id)
    assert kept_first is not None
    assert kept_first["clear_trigger"] == "sale"
    assert kept_first["cleared_at"] == _CLEARED_AT

    second_episode = store.get(
        no_sales_episode_document_id(_NO_SALES_MACHINE_ID, second_opened.event_id)
    )
    assert second_episode is not None
    assert second_episode["kind"] == "no_sales_episode"
    assert second_episode["opened_event_id"] == second_opened.event_id.value
    assert second_episode["cleared_at"] is None
    assert second_episode["clear_trigger"] is None
    assert second_episode["bypass_active"] is None


def test_opened_replay_does_not_clobber_cleared_episode() -> None:
    """edge: повтор того же Opened после Cleared не снимает поля снятия."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    store.upsert_from_event(opened)
    store.upsert_from_event(_no_sales_stale_cleared(clear_trigger="sale", bypass_active=False))
    store.upsert_from_event(opened)
    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is False


def test_cleared_with_trigger_upserts_episode_and_sticky() -> None:
    """happy: sale+bypass пишет sticky cleared и episode document."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=True)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "cleared"

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id)
    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is True
    expected_episode_id = f"no_sales_episode:{_NO_SALES_MACHINE_ID.value}:{opened.event_id.value}"
    assert episode["_id"] == expected_episode_id
    assert episode["opened_event_id"] == opened.event_id.value
    assert episode["assigned_technician_id"] == "tech-1"
    assert episode["assigned_technician_display"] == "Иван"
    assert "clearance_outcome" not in episode

    # bypass_active=None при trigger → False в эпизоде
    store.upsert_from_event(
        _no_sales_stale_cleared(clear_trigger="sale", bypass_active=None),
    )
    episode_none = store.get(episode_id)
    assert episode_none is not None
    assert episode_none["bypass_active"] is False

    # повтор upsert того же _id заменяет поля
    store.upsert_from_event(
        _no_sales_stale_cleared(clear_trigger="exclude", bypass_active=False),
    )
    replaced = store.get(episode_id)
    assert replaced is not None
    assert replaced["clear_trigger"] == "exclude"
    assert replaced["bypass_active"] is False


def test_cleared_without_trigger_upserts_episode() -> None:
    """error→happy (cycles): clear_trigger=None всё равно upsert episode + sticky cleared."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared()
    assert cleared.clear_trigger is None

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "cleared"

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id)
    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["clear_trigger"] is None


def test_cleared_with_trigger_null_bypass_stores_false() -> None:
    """edge: trigger заполнен, bypass_active=None → в episode bypass_active is False."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=None)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is False


def test_cleared_without_trigger_keeps_bypass_none() -> None:
    """edge: trigger пуст → bypass_active в episode остаётся None (не False)."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger=None, bypass_active=None)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["clear_trigger"] is None
    assert episode["bypass_active"] is None


def test_second_open_keeps_previous_episode() -> None:
    """edge: новое open затирает sticky open-полями, episode остаётся."""
    store = InMemorySalesMonitoringAuditStore()
    first_opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(first_opened)
    store.upsert_from_event(cleared)

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, first_opened.event_id)
    assert store.get(episode_id) is not None

    second_opened_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    second_opened = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{second_opened_at.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=second_opened_at,
        occurred_at=second_opened_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-2"),
        assigned_technician_display="Пётр",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    store.upsert_from_event(second_opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "open"
    assert sticky["opened_at"] == second_opened_at
    assert sticky["opened_event_id"] == second_opened.event_id.value

    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["opened_event_id"] == first_opened.event_id.value
    assert episode["clear_trigger"] == "sale"

    open_docs = store.list_open_no_sales()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == no_sales_audit_document_id(_NO_SALES_MACHINE_ID)


def test_list_no_sales_episodes_overlapping_includes_opened_or_cleared_in_period() -> None:
    """happy: эпизод попадает, если opened_at или cleared_at в [start, end]."""
    store = InMemorySalesMonitoringAuditStore()
    period_start = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 7, 28, 23, 59, tzinfo=UTC)

    # opened в периоде (opened=_OPENED_AT Jul 27, cleared=_CLEARED_AT Jul 28)
    in_by_opened = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(in_by_opened)

    # cleared в периоде, opened вне (до start)
    early_opened_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    early_opened_id = EventId(
        f"sales-monitoring-no-sales-stale-opened:early:{early_opened_at.isoformat()}"
    )
    in_by_cleared = _no_sales_stale_cleared(
        clear_trigger="exclude",
        bypass_active=False,
        opened_at=early_opened_at,
        opened_event_id=early_opened_id,
        cleared_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        machine_id=MachineId("102"),
    )
    store.upsert_from_event(in_by_cleared)

    # полностью вне периода
    outside = _no_sales_stale_cleared(
        clear_trigger="sale",
        bypass_active=False,
        opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        opened_event_id=EventId("sales-monitoring-no-sales-stale-opened:out:2026-06-01"),
        cleared_at=datetime(2026, 6, 2, 15, 0, tzinfo=UTC),
        machine_id=MachineId("103"),
    )
    store.upsert_from_event(outside)

    docs = store.list_no_sales_episodes_overlapping(start=period_start, end=period_end)
    assert len(docs) == 2
    machine_ids = {doc["machine_id"] for doc in docs}
    assert machine_ids == {_NO_SALES_MACHINE_ID.value, "102"}
    assert all(doc["kind"] == "no_sales_episode" for doc in docs)


def _assert_sticky_lists_exclude_episodes(
    store: InMemorySalesMonitoringAuditStore | MongoSalesMonitoringAuditStore,
) -> None:
    assert all(doc["kind"] == "no_sales" for doc in store.list_open_no_sales())
    cleared = store.list_cleared_no_sales_since(cleared_at_gte=_OPENED_AT)
    assert all(doc["kind"] == "no_sales" for doc in cleared)
    assert all(doc.get("kind") != "no_sales_episode" for doc in cleared)


def test_mongo_opened_upserts_sticky_and_open_episode() -> None:
    """happy: mongomock — Opened пишет sticky open и open-episode."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()

    store.upsert_from_event(opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert sticky is not None and sticky["status"] == "open"
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["opened_event_id"] == opened.event_id.value
    assert episode["cleared_at"] is None
    assert episode["clear_trigger"] is None
    assert episode["bypass_active"] is None
    assert "clearance_outcome" not in episode
    _assert_sticky_lists_exclude_episodes(store)


def test_mongo_second_open_keeps_first_episode_and_creates_second() -> None:
    """edge: mongomock — второе Opened сохраняет первый episode и создаёт второй."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    first_opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(first_opened)
    store.upsert_from_event(cleared)

    first_episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, first_opened.event_id)
    first_episode = store.get(first_episode_id)
    assert first_episode is not None
    assert first_episode["clear_trigger"] == "sale"

    second_opened_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    second_opened = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{second_opened_at.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=second_opened_at,
        occurred_at=second_opened_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-2"),
        assigned_technician_display="Пётр",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    store.upsert_from_event(second_opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["opened_event_id"] == second_opened.event_id.value

    kept_first = store.get(first_episode_id)
    assert kept_first is not None
    assert kept_first["clear_trigger"] == "sale"

    second_episode = store.get(
        no_sales_episode_document_id(_NO_SALES_MACHINE_ID, second_opened.event_id)
    )
    assert second_episode is not None
    assert second_episode["cleared_at"] is None
    assert second_episode["clear_trigger"] is None
    assert second_episode["bypass_active"] is None
    _assert_sticky_lists_exclude_episodes(store)


def test_mongo_opened_replay_does_not_clobber_cleared_episode() -> None:
    """edge: mongomock — повтор того же Opened после Cleared не снимает поля снятия."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()
    store.upsert_from_event(opened)
    store.upsert_from_event(_no_sales_stale_cleared(clear_trigger="sale", bypass_active=False))
    store.upsert_from_event(opened)
    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is False


def test_mongo_cleared_with_trigger_upserts_episode_and_sticky() -> None:
    """happy: mongomock dual-write sticky+episode; sticky-списки без episode."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=True)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "cleared"

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id)
    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is True
    expected_episode_id = f"no_sales_episode:{_NO_SALES_MACHINE_ID.value}:{opened.event_id.value}"
    assert episode["_id"] == expected_episode_id

    assert store.list_open_no_sales() == []
    _assert_sticky_lists_exclude_episodes(store)

    store.upsert_from_event(
        _no_sales_stale_cleared(clear_trigger="sale", bypass_active=None),
    )
    episode_none = store.get(episode_id)
    assert episode_none is not None
    assert episode_none["bypass_active"] is False

    store.upsert_from_event(
        _no_sales_stale_cleared(clear_trigger="exclude", bypass_active=False),
    )
    replaced = store.get(episode_id)
    assert replaced is not None
    assert replaced["clear_trigger"] == "exclude"
    assert replaced["bypass_active"] is False
    _assert_sticky_lists_exclude_episodes(store)


def test_mongo_second_open_keeps_previous_episode() -> None:
    """edge: mongomock — второе open не удаляет episode; list_open ровно один sticky."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    first_opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(first_opened)
    store.upsert_from_event(cleared)

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, first_opened.event_id)
    assert store.get(episode_id) is not None
    _assert_sticky_lists_exclude_episodes(store)

    second_opened_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    second_opened = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{second_opened_at.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=second_opened_at,
        occurred_at=second_opened_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-2"),
        assigned_technician_display="Пётр",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    store.upsert_from_event(second_opened)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "open"
    assert sticky["opened_at"] == second_opened_at
    assert sticky["opened_event_id"] == second_opened.event_id.value

    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["opened_event_id"] == first_opened.event_id.value
    assert episode["clear_trigger"] == "sale"

    open_docs = store.list_open_no_sales()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == no_sales_audit_document_id(_NO_SALES_MACHINE_ID)
    _assert_sticky_lists_exclude_episodes(store)


def test_mongo_cleared_without_trigger_upserts_episode() -> None:
    """error→happy (cycles): mongomock — clear_trigger=None upsert episode + sticky."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared()
    assert cleared.clear_trigger is None

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    sticky = store.get(no_sales_audit_document_id(_NO_SALES_MACHINE_ID))
    assert sticky is not None
    assert sticky["status"] == "cleared"

    episode_id = no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id)
    episode = store.get(episode_id)
    assert episode is not None
    assert episode["kind"] == "no_sales_episode"
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["clear_trigger"] is None
    _assert_sticky_lists_exclude_episodes(store)


def test_mongo_cleared_with_trigger_null_bypass_stores_false() -> None:
    """edge: mongomock — trigger заполнен, bypass=None → False в episode."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=None)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["clear_trigger"] == "sale"
    assert episode["bypass_active"] is False


def test_mongo_cleared_without_trigger_keeps_bypass_none() -> None:
    """edge: mongomock — trigger пуст → bypass_active остаётся None."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    opened = _no_sales_stale_opened()
    cleared = _no_sales_stale_cleared(clear_trigger=None, bypass_active=None)

    store.upsert_from_event(opened)
    store.upsert_from_event(cleared)

    episode = store.get(no_sales_episode_document_id(_NO_SALES_MACHINE_ID, opened.event_id))
    assert episode is not None
    assert episode["clear_trigger"] is None
    assert episode["bypass_active"] is None


def test_mongo_list_no_sales_episodes_overlapping_includes_opened_or_cleared_in_period() -> None:
    """happy: mongomock $or opened_at/cleared_at в периоде — как memory."""
    collection = mongomock.MongoClient().db.sales_monitoring_audit
    store = MongoSalesMonitoringAuditStore.from_collection(collection)
    period_start = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 7, 28, 23, 59, tzinfo=UTC)

    in_by_opened = _no_sales_stale_cleared(clear_trigger="sale", bypass_active=False)
    store.upsert_from_event(in_by_opened)

    early_opened_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    early_opened_id = EventId(
        f"sales-monitoring-no-sales-stale-opened:early:{early_opened_at.isoformat()}"
    )
    in_by_cleared = _no_sales_stale_cleared(
        clear_trigger="exclude",
        bypass_active=False,
        opened_at=early_opened_at,
        opened_event_id=early_opened_id,
        cleared_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        machine_id=MachineId("102"),
    )
    store.upsert_from_event(in_by_cleared)

    outside = _no_sales_stale_cleared(
        clear_trigger="sale",
        bypass_active=False,
        opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        opened_event_id=EventId("sales-monitoring-no-sales-stale-opened:out:2026-06-01"),
        cleared_at=datetime(2026, 6, 2, 15, 0, tzinfo=UTC),
        machine_id=MachineId("103"),
    )
    store.upsert_from_event(outside)

    docs = store.list_no_sales_episodes_overlapping(start=period_start, end=period_end)
    assert len(docs) == 2
    machine_ids = {doc["machine_id"] for doc in docs}
    assert machine_ids == {_NO_SALES_MACHINE_ID.value, "102"}
    assert all(doc["kind"] == "no_sales_episode" for doc in docs)
