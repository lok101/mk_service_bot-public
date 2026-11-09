from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.sales_monitoring.format_report import (
    ReportMachineLine,
    format_no_sales_status_board,
)
from src.application.sales_monitoring.incident_panel import open_no_sales_session_id
from src.application.sales_monitoring.no_sales_control import control_is_muted
from src.application.sales_monitoring.ports import (
    MachineSalesFreshnessLookup,
    SalesMonitoringAuditStore,
    StatusBoardPointerStore,
    StatusBoardTelegram,
)
from src.application.sales_monitoring.run_sales_report import CatalogMachine
from src.application.sales_monitoring.status_board_errors import (
    StatusBoardMessageGoneError,
    StatusBoardNotModifiedError,
    StatusBoardTelegramError,
)
from src.application.sales_monitoring.status_board_pointer import StatusBoardPointer
from src.domain.calendar import operational_day, operational_day_window
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)

__all__ = ["PublishNoSalesStatusBoard"]


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@beartype
def _line_for_open_doc(
    document: dict[str, object],
    *,
    catalog_by_id: dict[MachineId, CatalogMachine],
    freshness: MachineSalesFreshnessLookup,
) -> ReportMachineLine | None:
    machine_raw = document.get("machine_id")
    if not isinstance(machine_raw, str):
        return None
    machine_id = MachineId(machine_raw)
    last_sale_at = freshness.last_sale_at(machine_id)
    entry = catalog_by_id.get(machine_id)
    if entry is None:
        return None
    return ReportMachineLine(
        machine_id=machine_id,
        machine_name=entry.name,
        technician_display=entry.assigned_technician_display,
        last_sale_at=last_sale_at,
    )


@beartype
@dataclass(frozen=True, slots=True)
class PublishNoSalesStatusBoard:
    audit_store: SalesMonitoringAuditStore
    pointer_store: StatusBoardPointerStore
    telegram: StatusBoardTelegram
    freshness: MachineSalesFreshnessLookup
    chat_id: int

    @beartype
    def _cleared_lines(
        self,
        *,
        catalog_by_id: dict[MachineId, CatalogMachine],
        open_machine_ids: set[MachineId],
        now: datetime,
        operational_timezone: ZoneInfo,
        day_end_hour: int,
        excluded_codes: frozenset[str],
    ) -> list[ReportMachineLine]:
        ops_day = operational_day(now, operational_timezone, day_end_hour)
        start, end = operational_day_window(ops_day, operational_timezone, day_end_hour)
        try:
            cleared_docs = self.audit_store.list_cleared_no_sales_since(
                cleared_at_gte=start,
            )
        except Exception:
            _LOGGER.error(
                "no_sales_status_board_cleared_tail_failed",
                exc_info=True,
            )
            return []

        lines: list[ReportMachineLine] = []
        for document in cleared_docs:
            machine_raw = document.get("machine_id")
            if not isinstance(machine_raw, str):
                continue
            if machine_raw in excluded_codes:
                continue
            machine_id = MachineId(machine_raw)
            if machine_id in open_machine_ids:
                continue
            cleared_raw = document.get("cleared_at")
            if not isinstance(cleared_raw, datetime):
                continue
            if _ensure_aware(cleared_raw) >= end:
                continue
            line = _line_for_open_doc(
                document,
                catalog_by_id=catalog_by_id,
                freshness=self.freshness,
            )
            if line is not None:
                lines.append(line)
        return lines

    @beartype
    def _build_text(
        self,
        *,
        catalog: Sequence[CatalogMachine],
        now: datetime,
        timezone: ZoneInfo,
        stale_hours: int,
        last_sale_lookup_days: int,
        operational_timezone: ZoneInfo,
        day_end_hour: int,
        excluded_codes: frozenset[str],
    ) -> tuple[str, int, int]:
        catalog_by_id = {entry.machine_id: entry for entry in catalog}
        open_docs = list(self.audit_store.list_open_no_sales())
        lines: list[ReportMachineLine] = []
        open_machine_ids: set[MachineId] = set()
        for document in open_docs:
            machine_raw = document.get("machine_id")
            if not isinstance(machine_raw, str):
                continue
            if machine_raw in excluded_codes:
                continue
            machine_id = MachineId(machine_raw)
            opened_event_id = open_no_sales_session_id(document)
            if opened_event_id is not None and control_is_muted(
                self.audit_store.list_no_sales_controls(machine_id),
                machine_id=machine_id,
                opened_event_id=opened_event_id,
            ):
                open_machine_ids.add(machine_id)
                continue
            line = _line_for_open_doc(
                document,
                catalog_by_id=catalog_by_id,
                freshness=self.freshness,
            )
            if line is not None:
                lines.append(line)
                open_machine_ids.add(line.machine_id)

        cleared_lines = self._cleared_lines(
            catalog_by_id=catalog_by_id,
            open_machine_ids=open_machine_ids,
            now=now,
            operational_timezone=operational_timezone,
            day_end_hour=day_end_hour,
            excluded_codes=excluded_codes,
        )

        text = format_no_sales_status_board(
            lines=lines,
            cleared_lines=cleared_lines,
            stale_hours=stale_hours,
            now=now,
            timezone=timezone,
            last_sale_lookup_days=last_sale_lookup_days,
        )
        return text, len(lines), len(cleared_lines)

    @beartype
    def _save_pointer(
        self,
        *,
        message_id: int,
        text: str,
        posted_at: datetime,
    ) -> None:
        self.pointer_store.save(
            StatusBoardPointer(
                chat_id=self.chat_id,
                message_id=message_id,
                posted_at=posted_at,
                last_text=text,
            )
        )

    @beartype
    def execute(
        self,
        *,
        mode: Literal["sync", "rotate"],
        catalog: Sequence[CatalogMachine],
        now: datetime,
        timezone: ZoneInfo,
        stale_hours: int,
        last_sale_lookup_days: int,
        operational_timezone: ZoneInfo,
        day_end_hour: int,
        excluded_codes: frozenset[str] = frozenset(),
    ) -> None:
        if mode == "rotate":
            text, _open_count, cleared_count = self._build_text(
                catalog=catalog,
                now=now,
                timezone=timezone,
                stale_hours=stale_hours,
                last_sale_lookup_days=last_sale_lookup_days,
                operational_timezone=operational_timezone,
                day_end_hour=day_end_hour,
                excluded_codes=excluded_codes,
            )
            try:
                message_id = self.telegram.send_board(text)
            except StatusBoardTelegramError:
                _LOGGER.error(
                    "no_sales_status_board_telegram_failed",
                    exc_info=True,
                )
                return
            self._save_pointer(message_id=message_id, text=text, posted_at=now)
            _LOGGER.info(
                "no_sales_status_board_rotated",
                extra={
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                    "cleared_count": cleared_count,
                },
            )
            return

        pointer = self.pointer_store.load()
        text, open_count, cleared_count = self._build_text(
            catalog=catalog,
            now=now,
            timezone=timezone,
            stale_hours=stale_hours,
            last_sale_lookup_days=last_sale_lookup_days,
            operational_timezone=operational_timezone,
            day_end_hour=day_end_hour,
            excluded_codes=excluded_codes,
        )

        if pointer is None:
            try:
                message_id = self.telegram.send_board(text)
            except StatusBoardTelegramError:
                _LOGGER.error(
                    "no_sales_status_board_telegram_failed",
                    exc_info=True,
                )
                return
            self._save_pointer(message_id=message_id, text=text, posted_at=now)
            return

        if text == pointer.last_text:
            _LOGGER.info(
                "no_sales_status_board_skip_unchanged",
                extra={"message_id": pointer.message_id},
            )
            return

        try:
            self.telegram.edit_board(message_id=pointer.message_id, text=text)
        except StatusBoardNotModifiedError:
            _LOGGER.info(
                "no_sales_status_board_skip_unchanged",
                extra={"message_id": pointer.message_id},
            )
            return
        except StatusBoardMessageGoneError:
            try:
                message_id = self.telegram.send_board(text)
            except StatusBoardTelegramError:
                _LOGGER.error(
                    "no_sales_status_board_telegram_failed",
                    exc_info=True,
                )
                return
            self._save_pointer(message_id=message_id, text=text, posted_at=now)
            _LOGGER.info(
                "no_sales_status_board_recovered",
                extra={"message_id": message_id},
            )
            return
        except StatusBoardTelegramError:
            _LOGGER.error(
                "no_sales_status_board_telegram_failed",
                exc_info=True,
            )
            return

        self._save_pointer(
            message_id=pointer.message_id,
            text=text,
            posted_at=pointer.posted_at,
        )
        _LOGGER.info(
            "no_sales_status_board_edited",
            extra={
                "chat_id": self.chat_id,
                "message_id": pointer.message_id,
                "open_count": open_count,
                "cleared_count": cleared_count,
            },
        )
