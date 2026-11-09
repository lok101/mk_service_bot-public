from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.sales_monitoring.format_report import (
    ReportDeclineLine,
    ReportMachineLine,
    format_decline_sales_report,
    format_no_sales_status_board,
    format_ops_sales_report,
    status_board_telegram_html_length,
)
from src.domain.ids import MachineId

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MOSCOW = ZoneInfo("Europe/Moscow")


def test_ops_report_ignore_tail_uses_names_or_codes() -> None:
    text = format_ops_sales_report(
        no_sales=(),
        excluded_codes=("201", "999"),
        catalog_names={"201": "Excluded Named"},
        report_day=date(2026, 7, 27),
        branch="yesterday",
        timezone=_TZ,
        last_sale_lookup_days=10,
    )
    assert "Excluded Named" in text
    assert "999" in text
    assert "ignore" in text.lower() or "исключ" in text.lower()


def test_ops_report_grouped_by_technician_without_problem_subheaders() -> None:
    text = format_ops_sales_report(
        no_sales=(
            ReportMachineLine(
                machine_id=MachineId("162"),
                machine_name="СК Изумруд | Стачек, 3",
                technician_display="Дмитрий Мякотин",
                last_sale_at=datetime(2026, 7, 23, 16, 55, tzinfo=_MOSCOW),
            ),
        ),
        excluded_codes=(),
        catalog_names={},
        report_day=date(2026, 7, 28),
        branch="yesterday",
        timezone=_TZ,
        last_sale_lookup_days=10,
    )
    assert "🔹🔹🔹🔹🔹 Дмитрий Мякотин" in text
    assert "🔹🔹🔹🔹🔹 Дмитрий Мякотин 🔹" not in text
    assert "Нет продаж:" not in text
    assert "Падение продаж" not in text
    assert "🔹[162] СК Изумруд | Стачек, 3" in text
    assert "🔹Последняя продажа: 23.07 18:55" in text


def test_ops_report_unassigned_technician_uses_odd_diamond() -> None:
    text = format_ops_sales_report(
        no_sales=(
            ReportMachineLine(
                machine_id=MachineId("102"),
                machine_name="No Sales Loc",
                technician_display=None,
                last_sale_at=None,
            ),
        ),
        excluded_codes=(),
        catalog_names={},
        report_day=date(2026, 7, 27),
        branch="today",
        timezone=_TZ,
        last_sale_lookup_days=10,
    )
    assert "🔹🔹🔹🔹🔹 не закреплён" in text
    assert " 🔹🔹🔹🔹🔹" not in text
    assert "Нет продаж:" not in text
    assert "техник:" not in text
    assert "🔹Последняя продажа: более 10 дней назад" in text


def test_decline_report_flat_sorted_by_machine_id() -> None:
    text = format_decline_sales_report(
        declines=(
            ReportDeclineLine(
                machine_id=MachineId("124"),
                machine_name="ТЦ Марс",
                technician_display="Дмитрий Мякотин",
                report_sum=Decimal("10"),
                baseline_avg=Decimal("100"),
                drop_percent=89,
            ),
            ReportDeclineLine(
                machine_id=MachineId("120"),
                machine_name="Кировский",
                technician_display="Егор",
                report_sum=Decimal("20"),
                baseline_avg=Decimal("100"),
                drop_percent=40,
            ),
        ),
        report_day=date(2026, 7, 28),
    )
    assert text.startswith("Падение продаж за вчера (2026-07-28)")
    assert "🔹" not in text and "🔸" not in text
    assert "ignore" not in text.lower() and "исключ" not in text.lower()
    pos_120 = text.index("[120]")
    pos_124 = text.index("[124]")
    assert pos_120 < pos_124
    assert "техник: Егор" in text
    assert "техник: Дмитрий Мякотин" in text
    assert "Падение продаж за 28.07.26 на 40% (20 / 100)" in text
    assert "Падение продаж за 28.07.26 на 89% (10 / 100)" in text


def test_decline_report_empty_shows_no_declines_line() -> None:
    text = format_decline_sales_report(declines=(), report_day=date(2026, 7, 27))
    assert text == "Падение продаж за вчера (2026-07-27)\n\nПадений нет"


def test_decline_report_unassigned_technician_label() -> None:
    text = format_decline_sales_report(
        declines=(
            ReportDeclineLine(
                machine_id=MachineId("103"),
                machine_name="Only Decline",
                technician_display=None,
                report_sum=Decimal("1"),
                baseline_avg=Decimal("10"),
                drop_percent=90,
            ),
        ),
        report_day=date(2026, 7, 27),
    )
    assert "техник: не закреплён" in text


def test_decline_detail_truncates_fractional_baseline_without_avg_label() -> None:
    text = format_decline_sales_report(
        declines=(
            ReportDeclineLine(
                machine_id=MachineId("103"),
                machine_name="ТЦ Комсомолл, 1 эт | Сибирский тракт, 2",
                technician_display="Тест",
                report_sum=Decimal("992"),
                baseline_avg=Decimal("2457.666666666666666666666667"),
                drop_percent=60,
            ),
        ),
        report_day=date(2026, 8, 6),
    )
    assert "Падение продаж за 06.08.26 на 60% (992 / 2457)" in text
    assert "ср." not in text
    assert "2457.666" not in text


def test_decline_detail_shows_integer_counts_without_currency() -> None:
    text = format_decline_sales_report(
        declines=(
            ReportDeclineLine(
                machine_id=MachineId("120"),
                machine_name="Кировский",
                technician_display="Егор",
                report_sum=Decimal("12"),
                baseline_avg=Decimal("20"),
                drop_percent=40,
            ),
        ),
        report_day=date(2026, 7, 28),
    )
    assert "Падение продаж за 28.07.26 на 40% (12 / 20)" in text
    assert "₽" not in text
    assert "руб" not in text
    assert "шт." not in text


def test_status_board_empty_shows_none_and_stamp() -> None:
    """happy: пустой open-набор — заголовок, штамп TZ, «Проблемных нет»."""
    now = datetime(2026, 8, 24, 8, 0, tzinfo=_TZ)
    text = format_no_sales_status_board(
        lines=(),
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
    )
    assert text.startswith("Проблемные · порог 24 ч · обновлено 24.08 08:00")
    assert "Проблемных нет" in text
    assert "ещё " not in text


def test_status_board_groups_by_technician_like_ops() -> None:
    """happy: ромбы и last sale как ops-отчёт no_sales."""
    now = datetime(2026, 8, 24, 9, 0, tzinfo=_TZ)
    text = format_no_sales_status_board(
        lines=(
            ReportMachineLine(
                machine_id=MachineId("162"),
                machine_name="СК Изумруд | Стачек, 3",
                technician_display="Дмитрий Мякотин",
                last_sale_at=datetime(2026, 7, 23, 16, 55, tzinfo=_MOSCOW),
            ),
        ),
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=10,
    )
    assert "🔹🔹🔹🔹🔹 Дмитрий Мякотин" in text
    assert "🔹[162] СК Изумруд | Стачек, 3" in text
    assert "🔹Последняя продажа: 23.07 18:55" in text
    assert "Исключения" not in text
    assert "Проблемных нет" not in text


def test_status_board_truncates_with_more_n_under_4096() -> None:
    """edge: много строк → одно сообщение, хвост «ещё N», HTML ≤4096."""
    now = datetime(2026, 8, 24, 8, 0, tzinfo=_TZ)
    lines = tuple(
        ReportMachineLine(
            machine_id=MachineId(f"{index:04d}"),
            machine_name="N" * 90,
            technician_display="Техник А" if index < 40 else "Техник Б",
            last_sale_at=None,
        )
        for index in range(80)
    )
    text = format_no_sales_status_board(
        lines=lines,
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
    )
    assert "ещё " in text
    omitted = int(text.rsplit("ещё ", 1)[1].strip())
    assert omitted >= 1
    assert omitted < 80
    assert status_board_telegram_html_length(text) <= 4096
    assert text.count("Проблемные ·") == 1


def test_status_board_single_long_line_respects_html_limit() -> None:
    """edge: одна сверхдлинная строка + заголовок → HTML ≤ max_html_length."""
    now = datetime(2026, 8, 24, 8, 0, tzinfo=_TZ)
    long_name = "X" * 5000
    text = format_no_sales_status_board(
        lines=(
            ReportMachineLine(
                machine_id=MachineId("9999"),
                machine_name=long_name,
                technician_display="Техник",
                last_sale_at=None,
            ),
        ),
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
        max_html_length=200,
    )
    assert status_board_telegram_html_length(text) <= 200
    assert text.startswith("Проблемные")


def test_status_board_cleared_section_below_open_with_strike() -> None:
    """happy: open сверху; секция Снятые; machine-строки с U+0336."""
    now = datetime(2026, 8, 26, 10, 0, tzinfo=_TZ)
    open_line = ReportMachineLine(
        machine_id=MachineId("101"),
        machine_name="Open Cafe",
        technician_display="Иван",
        last_sale_at=datetime(2026, 8, 25, 8, 0, tzinfo=_TZ),
    )
    cleared_line = ReportMachineLine(
        machine_id=MachineId("202"),
        machine_name="Cleared Cafe",
        technician_display="Иван",
        last_sale_at=datetime(2026, 8, 26, 9, 0, tzinfo=_TZ),
    )
    text = format_no_sales_status_board(
        lines=(open_line,),
        cleared_lines=(cleared_line,),
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
    )
    assert "Проблемных нет" not in text
    open_pos = text.index("101")
    cleared_header = text.index("Снятые")
    # strike вставляет U+0336 между символами — contiguous "202" нет
    cleared_pos = text.index("2\u03360\u03362")
    assert open_pos < cleared_header < cleared_pos
    assert "\u0336" in text
    before = text[:cleared_header]
    assert "101" in before
    assert "\u0336" not in before.split("101")[0][-5:]


def test_status_board_cleared_only_omits_none_phrase() -> None:
    """edge: только cleared — без «Проблемных нет»."""
    now = datetime(2026, 8, 26, 10, 0, tzinfo=_TZ)
    cleared_line = ReportMachineLine(
        machine_id=MachineId("202"),
        machine_name="Cleared Cafe",
        technician_display="Петр",
        last_sale_at=datetime(2026, 8, 26, 9, 0, tzinfo=_TZ),
    )
    text = format_no_sales_status_board(
        lines=(),
        cleared_lines=(cleared_line,),
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
    )
    assert "Проблемных нет" not in text
    assert "Снятые" in text
    assert "\u0336" in text


def test_status_board_truncate_prefers_open_over_cleared() -> None:
    """edge: при малом max_html_length open остаётся; cleared режется / ещё N."""
    now = datetime(2026, 8, 26, 10, 0, tzinfo=_TZ)
    open_lines = tuple(
        ReportMachineLine(
            machine_id=MachineId(f"o{i}"),
            machine_name=f"Open {i} " + ("X" * 40),
            technician_display="Иван",
            last_sale_at=datetime(2026, 8, 25, 8, 0, tzinfo=_TZ),
        )
        for i in range(3)
    )
    cleared_lines = tuple(
        ReportMachineLine(
            machine_id=MachineId(f"c{i}"),
            machine_name=f"Cleared {i} " + ("Y" * 40),
            technician_display="Иван",
            last_sale_at=datetime(2026, 8, 26, 9, 0, tzinfo=_TZ),
        )
        for i in range(3)
    )
    full = format_no_sales_status_board(
        lines=open_lines,
        cleared_lines=cleared_lines,
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
    )
    tight = status_board_telegram_html_length(full) // 2
    text = format_no_sales_status_board(
        lines=open_lines,
        cleared_lines=cleared_lines,
        stale_hours=24,
        now=now,
        timezone=_TZ,
        last_sale_lookup_days=28,
        max_html_length=max(tight, 200),
    )
    assert "o0" in text or "Проблемные" in text
    if "Снятые" in text:
        before = text.split("Снятые", 1)[0]
        assert "o0" in before
    assert status_board_telegram_html_length(text) <= max(tight, 200)
