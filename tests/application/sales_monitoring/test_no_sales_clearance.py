from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.sales_monitoring.no_sales_clearance import (
    OUTCOME_EXCLUDED_MONITORING,
    OUTCOME_MANUAL,
    OUTCOME_PENDING,
    OUTCOME_SELF,
    OUTCOME_TECHNICIAN,
    no_sales_clearance_outcome,
    no_sales_episode_clear_kind,
    select_no_sales_history_documents,
)

_SALE = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
_WINDOW = 30


def test_clearance_pair_within_window_either_order_is_technician() -> None:
    """happy: completed до и после last_sale внутри окна → техник."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE + timedelta(minutes=10),),
            now=_SALE + timedelta(hours=2),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_TECHNICIAN
    )
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE - timedelta(minutes=10),),
            now=_SALE + timedelta(hours=2),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_TECHNICIAN
    )


def test_clearance_pair_exactly_on_window_boundary_is_technician() -> None:
    """happy: |Δ| == pair_minutes → техник."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE + timedelta(minutes=_WINDOW),),
            now=_SALE + timedelta(hours=2),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_TECHNICIAN
    )


def test_clearance_pending_inside_window_without_pair() -> None:
    """edge: now < last_sale + window, пары нет → ещё не ясно."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(),
            now=_SALE + timedelta(minutes=5),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_PENDING
    )


def test_clearance_self_after_window_without_pair() -> None:
    """edge: окно истекло без пары → само; completed после окна не спасает."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE + timedelta(minutes=_WINDOW + 1),),
            now=_SALE + timedelta(minutes=_WINDOW + 5),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_SELF
    )


def test_clearance_bypass_overrides_pair_and_exclude() -> None:
    """edge: bypass перекрывает пару и exclude."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=True,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE,),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == OUTCOME_MANUAL
    )
    assert (
        no_sales_clearance_outcome(
            clear_trigger="exclude",
            bypass_active=True,
            last_sale_at=_SALE,
            maintenance_completed_ats=(),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == OUTCOME_MANUAL
    )


def test_clearance_exclude_without_bypass_is_monitoring_off() -> None:
    """happy: exclude без обхода."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="exclude",
            bypass_active=False,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE,),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == OUTCOME_EXCLUDED_MONITORING
    )


def test_clearance_sale_without_last_sale_at_is_self() -> None:
    """error: sale и last_sale_at is None → само."""
    assert (
        no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=None,
            maintenance_completed_ats=(),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == OUTCOME_SELF
    )


_PERIOD_START = datetime(2026, 9, 22, 0, 0, tzinfo=UTC)
_PERIOD_END = datetime(2026, 9, 28, 23, 59, 59, tzinfo=UTC)


def test_history_open_sticky_deduped_when_episode_exists() -> None:
    """edge: open sticky с тем же opened_event_id, что у episode, не добавляется."""
    machine = "174"
    episode = {
        "kind": "no_sales_episode",
        "machine_id": machine,
        "opened_event_id": "open-same",
        "opened_at": datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        "cleared_at": None,
    }
    open_sticky = {
        "kind": "no_sales",
        "machine_id": machine,
        "opened_event_id": "open-same",
        "opened_at": datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        "status": "open",
    }
    selected = select_no_sales_history_documents(
        episodes=(episode,),
        open_documents=(open_sticky,),
        cleared_documents=(),
        start=_PERIOD_START,
        end=_PERIOD_END,
    )
    assert len(selected) == 1
    assert selected[0]["kind"] == "no_sales_episode"


def test_history_shows_two_episodes_and_open_sticky_same_machine() -> None:
    """happy: два эпизода одного machine_id + open sticky — три строки."""
    machine = "174"
    episode_a = {
        "kind": "no_sales_episode",
        "machine_id": machine,
        "opened_event_id": "open-a",
        "opened_at": datetime(2026, 9, 23, 10, 0, tzinfo=UTC),
        "cleared_at": datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    }
    episode_b = {
        "kind": "no_sales_episode",
        "machine_id": machine,
        "opened_event_id": "open-b",
        "opened_at": datetime(2026, 9, 25, 10, 0, tzinfo=UTC),
        "cleared_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
    }
    open_sticky = {
        "kind": "no_sales",
        "machine_id": machine,
        "opened_event_id": "open-c",
        "opened_at": datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        "status": "open",
    }
    selected = select_no_sales_history_documents(
        episodes=(episode_a, episode_b),
        open_documents=(open_sticky,),
        cleared_documents=(),
        start=_PERIOD_START,
        end=_PERIOD_END,
    )
    assert len(selected) == 3
    assert {doc["opened_event_id"] for doc in selected} == {"open-a", "open-b", "open-c"}
    assert all(doc["machine_id"] == machine for doc in selected)


def test_history_old_cleared_without_episode_shows_cleared() -> None:
    """edge: cleared sticky без эпизода остаётся; при наличии эпизода sticky не дублируется."""
    orphan_cleared = {
        "kind": "no_sales",
        "machine_id": "104",
        "opened_event_id": "legacy-open",
        "opened_at": datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
        "cleared_at": datetime(2026, 9, 24, 9, 0, tzinfo=UTC),
        "status": "cleared",
    }
    paired_episode = {
        "kind": "no_sales_episode",
        "machine_id": "188",
        "opened_event_id": "paired-open",
        "opened_at": datetime(2026, 9, 26, 8, 0, tzinfo=UTC),
        "cleared_at": datetime(2026, 9, 26, 9, 0, tzinfo=UTC),
    }
    paired_cleared = {
        "kind": "no_sales",
        "machine_id": "188",
        "opened_event_id": "paired-open",
        "opened_at": datetime(2026, 9, 26, 8, 0, tzinfo=UTC),
        "cleared_at": datetime(2026, 9, 26, 9, 0, tzinfo=UTC),
        "status": "cleared",
    }
    selected = select_no_sales_history_documents(
        episodes=(paired_episode,),
        open_documents=(),
        cleared_documents=(orphan_cleared, paired_cleared),
        start=_PERIOD_START,
        end=_PERIOD_END,
    )
    assert len(selected) == 2
    assert {doc["opened_event_id"] for doc in selected} == {"legacy-open", "paired-open"}
    kinds = {doc["opened_event_id"]: doc["kind"] for doc in selected}
    assert kinds["legacy-open"] == "no_sales"
    assert kinds["paired-open"] == "no_sales_episode"


def test_history_episode_without_trigger_with_sale_uses_sale_outcome() -> None:
    """edge: clear_trigger None + last_sale_at → как sale / bypass False (техник при паре)."""
    assert (
        no_sales_episode_clear_kind(
            cleared_at=_SALE + timedelta(hours=1),
            clear_trigger=None,
            bypass_active=None,
            last_sale_at=_SALE,
            maintenance_completed_ats=(_SALE + timedelta(minutes=5),),
            now=_SALE + timedelta(hours=2),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_TECHNICIAN
    )
    assert (
        no_sales_episode_clear_kind(
            cleared_at=_SALE + timedelta(hours=1),
            clear_trigger=None,
            bypass_active=True,
            last_sale_at=_SALE,
            maintenance_completed_ats=(),
            now=_SALE + timedelta(hours=2),
            pair_minutes=_WINDOW,
        )
        == OUTCOME_SELF
    )


def test_history_episode_without_trigger_without_sale_is_cleared() -> None:
    """edge: снятый episode без trigger и без last_sale_at → литерал cleared."""
    assert (
        no_sales_episode_clear_kind(
            cleared_at=_SALE,
            clear_trigger=None,
            bypass_active=None,
            last_sale_at=None,
            maintenance_completed_ats=(),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == "cleared"
    )


def test_history_open_episode_clear_kind_is_dash() -> None:
    """edge: cleared_at is None → '—' (не вызывать outcome)."""
    assert (
        no_sales_episode_clear_kind(
            cleared_at=None,
            clear_trigger=None,
            bypass_active=None,
            last_sale_at=None,
            maintenance_completed_ats=(),
            now=_SALE,
            pair_minutes=_WINDOW,
        )
        == "—"
    )
