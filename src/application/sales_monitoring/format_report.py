from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.ids import MachineId

ReportBranch = Literal["yesterday", "today"]

_DIAMOND_ODD = "🔹"
_DIAMOND_EVEN = "🔸"
_TELEGRAM_MAX_HTML = 4096
_PRE_OPEN = "<pre>"
_PRE_CLOSE = "</pre>"
_CLEARED_SECTION_HEADER = "Снятые"
_STRIKE = "\u0336"


@beartype
def _unicode_strikethrough(text: str) -> str:
    return "".join(f"{ch}{_STRIKE}" for ch in text)


@beartype
def _strike_technician_block_body(block: str) -> str:
    lines = block.split("\n")
    if not lines:
        return block
    return "\n".join([lines[0], *(_unicode_strikethrough(line) for line in lines[1:])])


@beartype
@dataclass(frozen=True, slots=True)
class ReportMachineLine:
    machine_id: MachineId
    machine_name: str | None
    technician_display: str | None
    last_sale_at: datetime | None = None


@beartype
@dataclass(frozen=True, slots=True)
class ReportDeclineLine:
    machine_id: MachineId
    machine_name: str | None
    technician_display: str | None
    report_sum: Decimal
    baseline_avg: Decimal
    drop_percent: int


@beartype
def _technician_group_name(display: str | None) -> str:
    if display is None or not display.strip():
        return "не закреплён"
    return display.strip()


@beartype
def _machine_label(line: ReportMachineLine | ReportDeclineLine) -> str:
    name = line.machine_name.strip() if line.machine_name else ""
    if name:
        return f"[{line.machine_id.value}] {name}"
    return f"[{line.machine_id.value}]"


@beartype
def _ignore_label(code: str, catalog_names: Mapping[str, str]) -> str:
    name = catalog_names.get(code)
    if name is not None and name.strip():
        return name.strip()
    return code


@beartype
def _localize(ts: datetime, timezone: ZoneInfo) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone)
    return ts.astimezone(timezone)


@beartype
def _format_short_datetime(ts: datetime, timezone: ZoneInfo) -> str:
    return _localize(ts, timezone).strftime("%d.%m %H:%M")


@beartype
def _format_last_sale(
    last_sale_at: datetime | None,
    *,
    timezone: ZoneInfo,
    last_sale_lookup_days: int,
) -> str:
    if last_sale_at is None:
        return f"Последняя продажа: более {last_sale_lookup_days} дней назад"
    return f"Последняя продажа: {_format_short_datetime(last_sale_at, timezone)}"


@beartype
def _format_count(value: Decimal) -> str:
    return str(int(value))


@beartype
def _format_decline_detail(line: ReportDeclineLine, *, report_day: date) -> str:
    day_label = report_day.strftime("%d.%m.%y")
    report = _format_count(line.report_sum)
    baseline = _format_count(line.baseline_avg)
    return f"Падение продаж за {day_label} на {line.drop_percent}% ({report} / {baseline})"


@beartype
def _diamond_for_index(index: int) -> str:
    return _DIAMOND_ODD if index % 2 == 0 else _DIAMOND_EVEN


@beartype
def _prefixed(diamond: str, text: str) -> str:
    return f"{diamond}{text}"


@beartype
def _ops_report_title(*, report_day: date, branch: ReportBranch) -> str:
    if branch == "yesterday":
        return f"Отчёт продаж за вчера ({report_day.isoformat()})"
    return f"Отчёт продаж за сегодня ({report_day.isoformat()})"


@beartype
def _collect_ops_technician_order(no_sales: Sequence[ReportMachineLine]) -> list[str]:
    names = {_technician_group_name(line.technician_display) for line in no_sales}
    return sorted(names, key=str.casefold)


@beartype
def _format_ops_technician_block(
    *,
    tech_name: str,
    diamond: str,
    no_sales: Sequence[ReportMachineLine],
    timezone: ZoneInfo,
    last_sale_lookup_days: int,
) -> str:
    lines: list[str] = [f"{diamond * 5} {tech_name}"]
    for index, item in enumerate(sorted(no_sales, key=lambda row: row.machine_id.value)):
        if index > 0:
            lines.append(diamond)
        lines.append(_prefixed(diamond, _machine_label(item)))
        lines.append(
            _prefixed(
                diamond,
                _format_last_sale(
                    item.last_sale_at,
                    timezone=timezone,
                    last_sale_lookup_days=last_sale_lookup_days,
                ),
            )
        )
    return "\n".join(lines)


@beartype
def status_board_telegram_html_length(plain: str) -> int:
    return len(_PRE_OPEN) + len(html.escape(plain)) + len(_PRE_CLOSE)


@beartype
def _status_board_title(*, stale_hours: int, now: datetime, timezone: ZoneInfo) -> str:
    stamp = _format_short_datetime(now, timezone)
    return f"Проблемные · порог {stale_hours} ч · обновлено {stamp}"


@beartype
def _fit_status_board_html(text: str, max_html_length: int) -> str:
    if status_board_telegram_html_length(text) <= max_html_length:
        return text
    lo = 0
    hi = len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid]
        if status_board_telegram_html_length(candidate) <= max_html_length:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


@beartype
def _truncate_status_board(
    *,
    title: str,
    tech_order: Sequence[str],
    by_tech: Mapping[str, Sequence[ReportMachineLine]],
    cleared_tech_order: Sequence[str],
    cleared_by_tech: Mapping[str, Sequence[ReportMachineLine]],
    timezone: ZoneInfo,
    last_sale_lookup_days: int,
    total_open: int,
    total_cleared: int,
    max_html_length: int,
) -> str:
    open_ordered: list[tuple[int, ReportMachineLine]] = []
    for tech_index, tech_name in enumerate(tech_order):
        group = sorted(
            by_tech.get(tech_name, ()),
            key=lambda row: row.machine_id.value,
        )
        for machine in group:
            open_ordered.append((tech_index, machine))

    cleared_ordered: list[tuple[int, ReportMachineLine]] = []
    for tech_index, tech_name in enumerate(cleared_tech_order):
        group = sorted(
            cleared_by_tech.get(tech_name, ()),
            key=lambda row: row.machine_id.value,
        )
        for machine in group:
            cleared_ordered.append((tech_index, machine))

    def render(
        open_prefix: Sequence[tuple[int, ReportMachineLine]],
        cleared_prefix: Sequence[tuple[int, ReportMachineLine]],
    ) -> str:
        omitted = total_open + total_cleared - len(open_prefix) - len(cleared_prefix)
        open_grouped: dict[str, list[ReportMachineLine]] = {}
        open_tech_indices: dict[str, int] = {}
        for tech_index, machine in open_prefix:
            name = _technician_group_name(machine.technician_display)
            open_grouped.setdefault(name, []).append(machine)
            open_tech_indices[name] = tech_index
        blocks: list[str] = [title]
        for tech_name in tech_order:
            tech_lines = open_grouped.get(tech_name)
            if not tech_lines:
                continue
            blocks.append(
                _format_ops_technician_block(
                    tech_name=tech_name,
                    diamond=_diamond_for_index(open_tech_indices[tech_name]),
                    no_sales=tech_lines,
                    timezone=timezone,
                    last_sale_lookup_days=last_sale_lookup_days,
                )
            )
        if cleared_prefix:
            cleared_grouped: dict[str, list[ReportMachineLine]] = {}
            cleared_tech_indices: dict[str, int] = {}
            for tech_index, machine in cleared_prefix:
                name = _technician_group_name(machine.technician_display)
                cleared_grouped.setdefault(name, []).append(machine)
                cleared_tech_indices[name] = tech_index
            blocks.append(_CLEARED_SECTION_HEADER)
            for tech_name in cleared_tech_order:
                tech_lines = cleared_grouped.get(tech_name)
                if not tech_lines:
                    continue
                block = _format_ops_technician_block(
                    tech_name=tech_name,
                    diamond=_diamond_for_index(cleared_tech_indices[tech_name]),
                    no_sales=tech_lines,
                    timezone=timezone,
                    last_sale_lookup_days=last_sale_lookup_days,
                )
                blocks.append(_strike_technician_block_body(block))
        if omitted > 0:
            blocks.append(f"ещё {omitted}")
        return "\n\n".join(blocks)

    best_open: Sequence[tuple[int, ReportMachineLine]] = ()
    last_ok = render((), ())
    for end in range(1, len(open_ordered) + 1):
        candidate = render(open_ordered[:end], ())
        if status_board_telegram_html_length(candidate) <= max_html_length:
            best_open = open_ordered[:end]
            last_ok = candidate
        else:
            break

    # Cleared только если все open уже уместились (не вытеснять open)
    if len(best_open) == len(open_ordered):
        for end in range(1, len(cleared_ordered) + 1):
            candidate = render(best_open, cleared_ordered[:end])
            if status_board_telegram_html_length(candidate) <= max_html_length:
                last_ok = candidate
            else:
                break

    if status_board_telegram_html_length(last_ok) <= max_html_length:
        return last_ok
    total_machines = total_open + total_cleared
    notice = f"{title}\n\nещё {total_machines}"
    if status_board_telegram_html_length(notice) <= max_html_length:
        return notice
    if status_board_telegram_html_length(title) <= max_html_length:
        return title
    return _fit_status_board_html(title, max_html_length)


@beartype
def format_no_sales_status_board(
    *,
    lines: Sequence[ReportMachineLine],
    cleared_lines: Sequence[ReportMachineLine] = (),
    stale_hours: int,
    now: datetime,
    timezone: ZoneInfo,
    last_sale_lookup_days: int,
    max_html_length: int = _TELEGRAM_MAX_HTML,
) -> str:
    title = _status_board_title(stale_hours=stale_hours, now=now, timezone=timezone)
    if not lines and not cleared_lines:
        return f"{title}\n\nПроблемных нет"

    by_tech: dict[str, list[ReportMachineLine]] = {}
    for line in lines:
        by_tech.setdefault(_technician_group_name(line.technician_display), []).append(line)
    tech_order = _collect_ops_technician_order(lines)
    blocks: list[str] = [title]
    for index, tech_name in enumerate(tech_order):
        tech_lines = by_tech.get(tech_name, ())
        if not tech_lines:
            continue
        blocks.append(
            _format_ops_technician_block(
                tech_name=tech_name,
                diamond=_diamond_for_index(index),
                no_sales=tech_lines,
                timezone=timezone,
                last_sale_lookup_days=last_sale_lookup_days,
            )
        )

    cleared_by_tech: dict[str, list[ReportMachineLine]] = {}
    for line in cleared_lines:
        cleared_by_tech.setdefault(
            _technician_group_name(line.technician_display),
            [],
        ).append(line)
    cleared_tech_order = _collect_ops_technician_order(cleared_lines)
    if cleared_lines:
        blocks.append(_CLEARED_SECTION_HEADER)
        for index, tech_name in enumerate(cleared_tech_order):
            tech_lines = cleared_by_tech.get(tech_name, ())
            if not tech_lines:
                continue
            block = _format_ops_technician_block(
                tech_name=tech_name,
                diamond=_diamond_for_index(index),
                no_sales=tech_lines,
                timezone=timezone,
                last_sale_lookup_days=last_sale_lookup_days,
            )
            blocks.append(_strike_technician_block_body(block))

    text = "\n\n".join(blocks)
    if status_board_telegram_html_length(text) <= max_html_length:
        return text
    return _truncate_status_board(
        title=title,
        tech_order=tech_order,
        by_tech=by_tech,
        cleared_tech_order=cleared_tech_order,
        cleared_by_tech=cleared_by_tech,
        timezone=timezone,
        last_sale_lookup_days=last_sale_lookup_days,
        total_open=len(lines),
        total_cleared=len(cleared_lines),
        max_html_length=max_html_length,
    )


@beartype
def format_ops_sales_report(
    *,
    no_sales: Sequence[ReportMachineLine],
    excluded_codes: Sequence[str],
    catalog_names: Mapping[str, str],
    report_day: date,
    branch: ReportBranch,
    timezone: ZoneInfo,
    last_sale_lookup_days: int,
) -> str:
    title = _ops_report_title(report_day=report_day, branch=branch)
    no_sales_by_tech: dict[str, list[ReportMachineLine]] = {}
    for no_sales_line in no_sales:
        no_sales_by_tech.setdefault(
            _technician_group_name(no_sales_line.technician_display),
            [],
        ).append(no_sales_line)

    tech_order = _collect_ops_technician_order(no_sales)
    blocks: list[str] = [title]
    for index, tech_name in enumerate(tech_order):
        tech_no_sales = no_sales_by_tech.get(tech_name, ())
        if not tech_no_sales:
            continue
        blocks.append(
            _format_ops_technician_block(
                tech_name=tech_name,
                diamond=_diamond_for_index(index),
                no_sales=tech_no_sales,
                timezone=timezone,
                last_sale_lookup_days=last_sale_lookup_days,
            )
        )

    ignore_labels = [_ignore_label(code, catalog_names) for code in excluded_codes]
    if ignore_labels:
        blocks.append("Исключения (ignore): " + ", ".join(ignore_labels))
    else:
        blocks.append("Исключения (ignore): —")

    return "\n\n".join(blocks)


@beartype
def format_decline_sales_report(
    *,
    declines: Sequence[ReportDeclineLine],
    report_day: date,
) -> str:
    title = f"Падение продаж за вчера ({report_day.isoformat()})"
    if not declines:
        return f"{title}\n\nПадений нет"

    blocks: list[str] = [title]
    sorted_declines = sorted(declines, key=lambda row: row.machine_id.value)
    for index, decline in enumerate(sorted_declines):
        technician = _technician_group_name(decline.technician_display)
        blocks.append(_machine_label(decline))
        blocks.append(f"техник: {technician}")
        blocks.append(_format_decline_detail(decline, report_day=report_day))
        if index < len(sorted_declines) - 1:
            blocks.append("")
    return "\n".join(blocks)
