from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.application.sales_monitoring.format_report import (
    ReportMachineLine,
    format_no_sales_status_board,
)
from src.application.sales_monitoring.no_sales_control import mute_document_id
from src.application.sales_monitoring.publish_no_sales_status_board import (
    PublishNoSalesStatusBoard,
)
from src.application.sales_monitoring.run_sales_report import CatalogMachine
from src.application.sales_monitoring.status_board_errors import (
    StatusBoardMessageGoneError,
    StatusBoardTelegramError,
)
from src.application.sales_monitoring.status_board_pointer import StatusBoardPointer
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.sales_monitoring.memory_status_board import (
    InMemoryStatusBoardPointerStore,
)

_TZ = ZoneInfo("Asia/Yekaterinburg")
_NOW = datetime(2026, 8, 24, 9, 0, tzinfo=_TZ)
_CHAT = -100
_MACHINE = MachineId("162")
_MUTED_MACHINE = MachineId("188")
_CLEARED_MACHINE = MachineId("303")
_OPENED_EVENT = "sales-monitoring-no-sales-stale-opened:162:2026-08-23"
_MUTED_OPENED_EVENT = "sales-monitoring-no-sales-stale-opened:188:2026-08-23"
_POSTED = datetime(2026, 8, 23, 8, 0, tzinfo=_TZ)
_STALE_HOURS = 12
_LOOKUP_DAYS = 28
_END_HOUR = 6


@dataclass
class _FakeAudit:
    docs: list[dict[str, object]] = field(default_factory=list)
    cleared_docs: list[dict[str, object]] = field(default_factory=list)
    controls: list[dict[str, object]] = field(default_factory=list)
    fail_cleared: bool = False

    def list_open_no_sales(self) -> list[dict[str, object]]:
        return list(self.docs)

    def list_cleared_no_sales_since(self, *, cleared_at_gte: datetime) -> list[dict[str, object]]:
        if self.fail_cleared:
            raise RuntimeError("cleared list failed")
        return [
            dict(doc)
            for doc in self.cleared_docs
            if isinstance(doc.get("cleared_at"), datetime) and doc["cleared_at"] >= cleared_at_gte
        ]

    def list_no_sales_controls(self, machine_id: MachineId) -> list[dict[str, object]]:
        return [dict(doc) for doc in self.controls if doc.get("machine_id") == machine_id.value]

    def upsert_from_event(self, event: object) -> None:
        del event

    def list_open_offline(self) -> list[dict[str, object]]:
        return []

    def list_no_sales_episodes_overlapping(
        self, *, start: datetime, end: datetime
    ) -> list[dict[str, object]]:
        del start, end
        return []


@dataclass
class _FakeFreshness:
    last: dict[MachineId, datetime | None] = field(default_factory=dict)

    def last_sale_at(self, machine_id: MachineId) -> datetime | None:
        return self.last.get(machine_id)

    def global_sales_cursor(self) -> datetime | None:
        return _NOW


@dataclass
class _FakeTelegram:
    sent: list[str] = field(default_factory=list)
    edits: list[tuple[int, str]] = field(default_factory=list)
    next_id: int = 1
    gone: bool = False
    fail_send: bool = False
    fail_edit: bool = False

    def send_board(self, text: str) -> int:
        if self.fail_send:
            raise StatusBoardTelegramError("send failed")
        self.sent.append(text)
        message_id = self.next_id
        self.next_id += 1
        return message_id

    def edit_board(self, *, message_id: int, text: str) -> None:
        if self.gone:
            raise StatusBoardMessageGoneError("gone")
        if self.fail_edit:
            raise StatusBoardTelegramError("edit failed")
        self.edits.append((message_id, text))


def _catalog() -> tuple[CatalogMachine, ...]:
    return (
        CatalogMachine(
            machine_id=_MACHINE,
            name="СК Изумруд",
            assigned_technician_id=TechnicianId("t1"),
            assigned_technician_display="Иван",
        ),
    )


def _catalog_with_muted() -> tuple[CatalogMachine, ...]:
    return (
        *_catalog(),
        CatalogMachine(
            machine_id=_MUTED_MACHINE,
            name="Muted Cafe",
            assigned_technician_id=TechnicianId("t1"),
            assigned_technician_display="Иван",
        ),
    )


def _catalog_with_cleared() -> tuple[CatalogMachine, ...]:
    return (
        CatalogMachine(
            machine_id=_MACHINE,
            name="СК Изумруд",
            assigned_technician_id=TechnicianId("t1"),
            assigned_technician_display="Иван",
        ),
        CatalogMachine(
            machine_id=_CLEARED_MACHINE,
            name="Cleared Cafe",
            assigned_technician_id=TechnicianId("t1"),
            assigned_technician_display="Иван",
        ),
    )


def _open_doc(
    *,
    machine_id: MachineId = _MACHINE,
    opened_event_id: str = _OPENED_EVENT,
) -> dict[str, object]:
    return {
        "machine_id": machine_id.value,
        "kind": "no_sales",
        "status": "open",
        "opened_event_id": opened_event_id,
    }


def _mute_control(
    *,
    machine_id: MachineId,
    opened_event_id: str,
) -> dict[str, object]:
    mute_id = mute_document_id(machine_id, opened_event_id)
    return {
        "_id": mute_id,
        "kind": "no_sales_mute",
        "machine_id": machine_id.value,
        "opened_event_id": opened_event_id,
    }


def _cleared_doc(
    *,
    cleared_at: datetime,
    last_sale_at: datetime | None,
    machine_id: MachineId = _CLEARED_MACHINE,
) -> dict[str, object]:
    return {
        "machine_id": machine_id.value,
        "kind": "no_sales",
        "status": "cleared",
        "cleared_at": cleared_at,
        "last_sale_at": last_sale_at,
    }


def _build_use_case(
    *,
    audit: _FakeAudit | None = None,
    pointer_store: InMemoryStatusBoardPointerStore | None = None,
    telegram: _FakeTelegram | None = None,
    freshness: _FakeFreshness | None = None,
) -> tuple[
    PublishNoSalesStatusBoard,
    _FakeAudit,
    InMemoryStatusBoardPointerStore,
    _FakeTelegram,
    _FakeFreshness,
]:
    audit_obj = audit if audit is not None else _FakeAudit(docs=[_open_doc()])
    store = pointer_store if pointer_store is not None else InMemoryStatusBoardPointerStore()
    tg = telegram if telegram is not None else _FakeTelegram()
    fresh = (
        freshness
        if freshness is not None
        else _FakeFreshness(last={_MACHINE: datetime(2026, 8, 23, 12, 0, tzinfo=_TZ)})
    )
    use_case = PublishNoSalesStatusBoard(
        audit_store=audit_obj,
        pointer_store=store,
        telegram=tg,
        freshness=fresh,
        chat_id=_CHAT,
    )
    return use_case, audit_obj, store, tg, fresh


def test_publish_status_board_recovers_from_malformed_pointer() -> None:
    use_case, _, store, telegram, _ = _build_use_case()
    assert store.load() is None
    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert len(telegram.sent) == 1
    assert store.load() is not None


def test_publish_sync_without_pointer_sends_and_saves() -> None:
    use_case, _, store, telegram, _ = _build_use_case()

    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    assert len(telegram.sent) == 1
    assert "162" in telegram.sent[0]
    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 1
    assert telegram.edits == []


def test_publish_sync_with_pointer_edits() -> None:
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=10,
            posted_at=_NOW,
            last_text="old",
        )
    )
    use_case, _, store, telegram, _ = _build_use_case(pointer_store=store)

    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    assert telegram.sent == []
    assert len(telegram.edits) == 1
    message_id, new_text = telegram.edits[0]
    assert message_id == 10
    assert "162" in new_text
    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 10
    assert pointer.last_text == new_text


def test_publish_sync_identical_text_skips_http(caplog: pytest.LogCaptureFixture) -> None:
    use_case, _, _, telegram, _ = _build_use_case()

    with caplog.at_level("INFO"):
        use_case.execute(
            mode="sync",
            catalog=_catalog(),
            now=_NOW,
            timezone=_TZ,
            stale_hours=_STALE_HOURS,
            last_sale_lookup_days=_LOOKUP_DAYS,
            operational_timezone=_TZ,
            day_end_hour=_END_HOUR,
        )
        use_case.execute(
            mode="sync",
            catalog=_catalog(),
            now=_NOW,
            timezone=_TZ,
            stale_hours=_STALE_HOURS,
            last_sale_lookup_days=_LOOKUP_DAYS,
            operational_timezone=_TZ,
            day_end_hour=_END_HOUR,
        )

    assert len(telegram.sent) == 1
    assert telegram.edits == []
    assert any(
        record.message == "no_sales_status_board_skip_unchanged" and record.levelname == "INFO"
        for record in caplog.records
    )


def test_publish_rotate_always_sends_new_message() -> None:
    last_sale = datetime(2026, 8, 23, 12, 0, tzinfo=_TZ)
    board_text = format_no_sales_status_board(
        lines=(
            ReportMachineLine(
                machine_id=_MACHINE,
                machine_name="СК Изумруд",
                technician_display="Иван",
                last_sale_at=last_sale,
            ),
        ),
        stale_hours=_STALE_HOURS,
        now=_NOW,
        timezone=_TZ,
        last_sale_lookup_days=_LOOKUP_DAYS,
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=10,
            posted_at=_NOW,
            last_text=board_text,
        )
    )
    telegram = _FakeTelegram(next_id=20)
    use_case, _, store, telegram, _ = _build_use_case(
        pointer_store=store,
        telegram=telegram,
        freshness=_FakeFreshness(last={_MACHINE: last_sale}),
    )

    use_case.execute(
        mode="rotate",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    assert len(telegram.sent) == 1
    assert telegram.edits == []
    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 20
    assert pointer.message_id != 10
    assert pointer.last_text == board_text


def test_publish_sync_edit_gone_sends_and_saves(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=10,
            posted_at=_NOW,
            last_text="old",
        )
    )
    telegram = _FakeTelegram(next_id=30, gone=True)
    use_case, _, store, telegram, _ = _build_use_case(
        pointer_store=store,
        telegram=telegram,
    )

    with caplog.at_level("INFO"):
        use_case.execute(
            mode="sync",
            catalog=_catalog(),
            now=_NOW,
            timezone=_TZ,
            stale_hours=_STALE_HOURS,
            last_sale_lookup_days=_LOOKUP_DAYS,
            operational_timezone=_TZ,
            day_end_hour=_END_HOUR,
        )

    assert len(telegram.sent) == 1
    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 30
    assert pointer.message_id != 10
    assert any(record.message == "no_sales_status_board_recovered" for record in caplog.records)


def test_publish_telegram_fail_keeps_pointer(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=10,
            posted_at=_NOW,
            last_text="old",
        )
    )
    use_case, _, store, _, _ = _build_use_case(
        pointer_store=store,
        telegram=_FakeTelegram(fail_edit=True),
    )

    with caplog.at_level("ERROR"):
        use_case.execute(
            mode="sync",
            catalog=_catalog(),
            now=_NOW,
            timezone=_TZ,
            stale_hours=_STALE_HOURS,
            last_sale_lookup_days=_LOOKUP_DAYS,
            operational_timezone=_TZ,
            day_end_hour=_END_HOUR,
        )

    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 10
    assert any(
        record.message == "no_sales_status_board_telegram_failed" and record.levelname == "ERROR"
        for record in caplog.records
    )


def test_publish_rotate_fail_keeps_old_pointer() -> None:
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=10,
            posted_at=_NOW,
            last_text="old",
        )
    )
    use_case, _, store, _, _ = _build_use_case(
        pointer_store=store,
        telegram=_FakeTelegram(fail_send=True),
    )

    use_case.execute(
        mode="rotate",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    pointer = store.load()
    assert pointer is not None
    assert pointer.message_id == 10
    assert pointer.last_text == "old"


def test_publish_sync_includes_cleared_in_operational_day() -> None:
    """happy: cleared_at внутри текущего ops-day → секция «Снятые» в sync edit."""
    cleared_at = datetime(2026, 8, 24, 7, 0, tzinfo=_TZ)
    audit = _FakeAudit(
        docs=[_open_doc()],
        cleared_docs=[_cleared_doc(cleared_at=cleared_at, last_sale_at=None)],
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=1,
            posted_at=_POSTED,
            last_text="old",
        )
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit, pointer_store=store)
    use_case.execute(
        mode="sync",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert telegram.edits
    assert "Снятые" in telegram.edits[0][1]


def test_publish_omits_cleared_outside_operational_day() -> None:
    """edge: cleared_at вне ops-day window → нет «Снятые»."""
    cleared_at = datetime(2026, 8, 23, 10, 0, tzinfo=_TZ)
    audit = _FakeAudit(
        docs=[_open_doc()],
        cleared_docs=[_cleared_doc(cleared_at=cleared_at, last_sale_at=None)],
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=1,
            posted_at=_POSTED,
            last_text="old",
        )
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit, pointer_store=store)
    use_case.execute(
        mode="sync",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    text = telegram.edits[0][1] if telegram.edits else telegram.sent[-1]
    assert "Снятые" not in text


def test_publish_rotate_includes_ops_day_cleared() -> None:
    """happy: rotate включает cleared текущего ops-day."""
    cleared_at = datetime(2026, 8, 24, 7, 0, tzinfo=_TZ)
    audit = _FakeAudit(
        docs=[],
        cleared_docs=[_cleared_doc(cleared_at=cleared_at, last_sale_at=None)],
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit)
    use_case.execute(
        mode="rotate",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert telegram.sent
    assert "Снятые" in telegram.sent[-1]


def test_publish_rotate_includes_same_ops_day_clear_before_rotate() -> None:
    """happy: clear 06:30 при END_HOUR=6 виден на rotate 08:00."""
    now = datetime(2026, 8, 24, 8, 0, tzinfo=_TZ)
    cleared_at = datetime(2026, 8, 24, 6, 30, tzinfo=_TZ)
    audit = _FakeAudit(
        docs=[],
        cleared_docs=[_cleared_doc(cleared_at=cleared_at, last_sale_at=None)],
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit)
    use_case.execute(
        mode="rotate",
        catalog=_catalog_with_cleared(),
        now=now,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert "Снятые" in telegram.sent[-1]


def test_publish_sync_bootstrap_includes_ops_day_cleared() -> None:
    """happy: нет pointer — sync send включает cleared ops-day."""
    cleared_at = datetime(2026, 8, 24, 7, 0, tzinfo=_TZ)
    audit = _FakeAudit(
        docs=[],
        cleared_docs=[_cleared_doc(cleared_at=cleared_at, last_sale_at=None)],
    )
    use_case, _, store, telegram, _ = _build_use_case(audit=audit)
    assert store.load() is None
    use_case.execute(
        mode="sync",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert telegram.sent
    assert "Снятые" in telegram.sent[-1]


def test_publish_sync_excludes_open_from_cleared_tail() -> None:
    """edge: open machine не попадает в хвост «Снятые»."""
    same = _MACHINE
    audit = _FakeAudit(
        docs=[_open_doc()],
        cleared_docs=[
            _cleared_doc(
                machine_id=same,
                cleared_at=datetime(2026, 8, 24, 7, 0, tzinfo=_TZ),
                last_sale_at=None,
            ),
        ],
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(StatusBoardPointer(chat_id=_CHAT, message_id=7, posted_at=_POSTED, last_text="old"))
    tg = _FakeTelegram()
    use_case, *_ = _build_use_case(audit=audit, pointer_store=store, telegram=tg)
    use_case.execute(
        mode="sync",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    _mid, text = tg.edits[0]
    assert "162" in text  # open
    assert "Снятые" not in text


def test_publish_sync_cleared_list_fail_publishes_open_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """error: list cleared raise → open всё равно в edit; ERROR log."""
    audit = _FakeAudit(docs=[_open_doc()], fail_cleared=True)
    store = InMemoryStatusBoardPointerStore()
    store.save(StatusBoardPointer(chat_id=_CHAT, message_id=7, posted_at=_POSTED, last_text="old"))
    tg = _FakeTelegram()
    use_case, *_ = _build_use_case(audit=audit, pointer_store=store, telegram=tg)
    with caplog.at_level(logging.ERROR):
        use_case.execute(
            mode="sync",
            catalog=_catalog(),
            now=_NOW,
            timezone=_TZ,
            stale_hours=_STALE_HOURS,
            last_sale_lookup_days=_LOOKUP_DAYS,
            operational_timezone=_TZ,
            day_end_hour=_END_HOUR,
        )
    assert tg.edits
    assert "162" in tg.edits[0][1]
    assert "Снятые" not in tg.edits[0][1]
    assert any("no_sales_status_board_cleared_tail_failed" in r.message for r in caplog.records)


def test_publish_sync_skips_excluded_open() -> None:
    """happy: machine в excluded_codes не в тексте open."""
    store = InMemoryStatusBoardPointerStore()
    store.save(StatusBoardPointer(chat_id=_CHAT, message_id=7, posted_at=_POSTED, last_text="old"))
    tg = _FakeTelegram()
    use_case, *_ = _build_use_case(pointer_store=store, telegram=tg)

    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
        excluded_codes=frozenset({_MACHINE.value}),
    )

    assert tg.edits
    text = tg.edits[0][1]
    assert "162" not in text
    assert "Проблемных нет" in text or "нет" in text.lower()


def test_publish_sync_skips_excluded_cleared_tail() -> None:
    """edge: excluded cleared не в хвосте «Снятые»."""
    audit = _FakeAudit(
        docs=[],
        cleared_docs=[
            _cleared_doc(
                cleared_at=_NOW - timedelta(hours=1),
                last_sale_at=_NOW - timedelta(hours=1),
            )
        ],
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(StatusBoardPointer(chat_id=_CHAT, message_id=7, posted_at=_POSTED, last_text="old"))
    tg = _FakeTelegram()
    use_case, *_ = _build_use_case(audit=audit, pointer_store=store, telegram=tg)

    use_case.execute(
        mode="sync",
        catalog=_catalog_with_cleared(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
        excluded_codes=frozenset({_CLEARED_MACHINE.value}),
    )

    assert tg.edits
    text = tg.edits[0][1]
    assert "Снятые" not in text
    assert "303" not in text


def test_publish_omits_open_sticky_outside_coffee_catalog() -> None:
    """happy: open sticky вне coffee catalog не попадает в текст сводки."""
    snack = MachineId("501")
    audit = _FakeAudit(
        docs=[
            _open_doc(),
            {"machine_id": snack.value, "kind": "no_sales", "status": "open"},
        ]
    )
    freshness = _FakeFreshness(
        last={
            _MACHINE: datetime(2026, 8, 23, 12, 0, tzinfo=_TZ),
            snack: datetime(2026, 8, 23, 12, 0, tzinfo=_TZ),
        }
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit, freshness=freshness)
    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert telegram.sent
    text = telegram.sent[0]
    assert "162" in text
    assert "501" not in text


def test_publish_omits_cleared_sticky_outside_coffee_catalog() -> None:
    """edge: cleared sticky вне coffee catalog не в хвосте «Снятые»."""
    snack = MachineId("501")
    audit = _FakeAudit(
        docs=[],
        cleared_docs=[
            _cleared_doc(
                cleared_at=_NOW - timedelta(hours=1),
                last_sale_at=_NOW - timedelta(hours=1),
                machine_id=snack,
            )
        ],
    )
    store = InMemoryStatusBoardPointerStore()
    store.save(
        StatusBoardPointer(
            chat_id=_CHAT,
            message_id=7,
            posted_at=_POSTED,
            last_text="old",
        )
    )
    tg = _FakeTelegram()
    use_case, *_ = _build_use_case(audit=audit, pointer_store=store, telegram=tg)
    use_case.execute(
        mode="sync",
        catalog=_catalog(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert tg.edits
    text = tg.edits[0][1]
    assert "501" not in text
    assert "5\u03360\u03361" not in text


def test_publish_omits_muted_machine_from_no_sales_board() -> None:
    """happy: заглушенный аппарат не попадает в TG no-sales board."""
    audit = _FakeAudit(
        docs=[
            _open_doc(),
            _open_doc(machine_id=_MUTED_MACHINE, opened_event_id=_MUTED_OPENED_EVENT),
        ],
        controls=[_mute_control(machine_id=_MUTED_MACHINE, opened_event_id=_MUTED_OPENED_EVENT)],
    )
    freshness = _FakeFreshness(
        last={
            _MACHINE: datetime(2026, 8, 23, 12, 0, tzinfo=_TZ),
            _MUTED_MACHINE: datetime(2026, 8, 23, 11, 0, tzinfo=_TZ),
        }
    )
    use_case, _, _, telegram, _ = _build_use_case(audit=audit, freshness=freshness)

    use_case.execute(
        mode="sync",
        catalog=_catalog_with_muted(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    assert len(telegram.sent) == 1
    text = telegram.sent[0]
    assert "162" in text
    assert "188" not in text
    assert "Muted Cafe" not in text


def test_publish_all_muted_shows_no_problems() -> None:
    """edge: все open заглушены — board без списка проблем («Проблемных нет»)."""
    audit = _FakeAudit(
        docs=[_open_doc(machine_id=_MUTED_MACHINE, opened_event_id=_MUTED_OPENED_EVENT)],
        controls=[_mute_control(machine_id=_MUTED_MACHINE, opened_event_id=_MUTED_OPENED_EVENT)],
    )
    freshness = _FakeFreshness(last={_MUTED_MACHINE: datetime(2026, 8, 23, 11, 0, tzinfo=_TZ)})
    use_case, _, _, telegram, _ = _build_use_case(audit=audit, freshness=freshness)

    use_case.execute(
        mode="sync",
        catalog=_catalog_with_muted(),
        now=_NOW,
        timezone=_TZ,
        stale_hours=_STALE_HOURS,
        last_sale_lookup_days=_LOOKUP_DAYS,
        operational_timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    assert len(telegram.sent) == 1
    text = telegram.sent[0]
    assert "Проблемных нет" in text
    assert "188" not in text
    assert "Muted Cafe" not in text
