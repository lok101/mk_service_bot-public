from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from scripts.settlement_admin_lib.formatters import (
    batch_exit_code,
    format_cli_datetime,
    format_cli_decimal_map_lines,
    print_batch_preview,
    print_preview,
)

from src.application.technician_settlement.preview_all_reconciliations import (
    PreviewAllTechniciansResult,
    TechnicianPreviewOutcome,
)
from src.application.technician_settlement.preview_reconciliation import ReconciliationPreview
from src.application.technician_warehouse.ports import UnmatchedMsProduct
from src.domain.ids import TechnicianId


def test_format_cli_datetime_uses_local_timezone() -> None:
    value = datetime(2026, 7, 9, 7, 59, 27, tzinfo=UTC)
    assert format_cli_datetime(value, ZoneInfo("Asia/Yekaterinburg")) == "2026-07-09 12:59:27"


def test_format_cli_decimal_map_lines_aligns_and_uses_comma() -> None:
    lines = format_cli_decimal_map_lines(
        "residual",
        {
            "coffee": Decimal("-240"),
            "milk": Decimal("12.5"),
        },
    )
    assert lines == [
        "residual:",
        "  coffee  -240",
        "  milk    12,5",
    ]


def test_format_cli_decimal_map_lines_empty() -> None:
    assert format_cli_decimal_map_lines("warehouse_delta", {}) == ["warehouse_delta:", "  (none)"]


def test_print_preview_shows_session_cutoff_not_anchor_at(capsys) -> None:
    """happy: label session_cutoff:; нет строки anchor_at:."""
    preview = ReconciliationPreview(
        technician_id=TechnicianId("10003"),
        anchor_at=datetime(2026, 7, 9, 7, 59, 27, tzinfo=UTC),
        scope=(),
        deferred=(),
        ledger_balance_session={},
        warehouse_inventory_id="inv-42",
        warehouse_inventory_moment=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(),
        blockers=(),
        can_finalize=True,
        residual_by_sku={},
    )
    print_preview(
        preview,
        audit_timezone=ZoneInfo("Asia/Yekaterinburg"),
    )
    out = capsys.readouterr().out
    assert "session_cutoff: 2026-07-09 12:59:27" in out
    assert "anchor_at:" not in out


def test_print_preview_body_has_no_unmatched_products_section(capsys) -> None:
    """edge ATH-008: секция unmatched_products отсутствует даже если поле DTO непустое."""
    preview = ReconciliationPreview(
        technician_id=TechnicianId("10003"),
        anchor_at=datetime(2026, 7, 9, 7, 59, 27, tzinfo=UTC),
        scope=(),
        deferred=(),
        ledger_balance_session={},
        warehouse_inventory_id="inv-42",
        warehouse_inventory_moment=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(
            UnmatchedMsProduct(
                product_code="MS-9",
                product_name="Неизвестный товар",
                external_document_id="doc-9",
            ),
        ),
        blockers=(),
        can_finalize=True,
        residual_by_sku={},
    )
    print_preview(
        preview,
        audit_timezone=ZoneInfo("Asia/Yekaterinburg"),
    )
    out = capsys.readouterr().out
    assert "unmatched_products:" not in out


def test_print_preview_human_readable(capsys) -> None:
    preview = ReconciliationPreview(
        technician_id=TechnicianId("10003"),
        anchor_at=datetime(2026, 7, 9, 7, 59, 27, tzinfo=UTC),
        scope=(),
        deferred=(),
        ledger_balance_session={"coffee": Decimal("-240")},
        warehouse_inventory_id="inv-42",
        warehouse_inventory_moment=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(
            UnmatchedMsProduct(
                product_code="MS-9",
                product_name="Неизвестный товар",
                external_document_id="doc-9",
            ),
        ),
        blockers=(),
        can_finalize=True,
        residual_by_sku={"coffee": Decimal("760")},
    )
    print_preview(
        preview,
        audit_timezone=ZoneInfo("Asia/Yekaterinburg"),
    )
    output = capsys.readouterr().out
    assert "session_cutoff: 2026-07-09 12:59:27" in output
    assert "anchor_at:" not in output
    assert "[scope]" in output
    assert "(none)" in output
    assert "[deferred]" in output
    assert "warehouse_inventory_id: inv-42" in output
    assert "warehouse_source: domain_technician_warehouse" in output
    assert "ledger_balance_session:" in output
    assert "  coffee  -240" in output
    assert "warehouse_delta:" in output
    assert "  coffee  1000" in output
    assert "residual:" in output
    assert "  coffee  760" in output
    assert "unmatched_products:" not in output
    assert "period_id" not in output
    assert "{" not in output


def _minimal_preview(*, technician_id: str = "10003") -> ReconciliationPreview:
    return ReconciliationPreview(
        technician_id=TechnicianId(technician_id),
        anchor_at=datetime(2026, 7, 9, 7, 59, 27, tzinfo=UTC),
        scope=(),
        deferred=(),
        ledger_balance_session={},
        warehouse_inventory_id="inv-1",
        warehouse_inventory_moment=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(),
        blockers=(),
        can_finalize=True,
        residual_by_sku={},
    )


def test_print_batch_preview_includes_summary_and_counters(capsys) -> None:
    preview = _minimal_preview()
    result = PreviewAllTechniciansResult(
        outcomes=(
            TechnicianPreviewOutcome(
                technician_id=TechnicianId("10003"),
                technician_name="Ivan",
                status="ok",
                reason="",
                preview=preview,
            ),
            TechnicianPreviewOutcome(
                technician_id=TechnicianId("10010"),
                technician_name="Petr",
                status="blocked",
                reason="no warehouse delta for reconciliation window",
                preview=None,
            ),
        ),
    )
    print_batch_preview(
        result,
        audit_timezone=ZoneInfo("Asia/Yekaterinburg"),
    )
    output = capsys.readouterr().out
    assert "anchor_at:" not in output
    assert "=== technician_id=10003 technician_name=Ivan ===" in output
    assert "[scope]" in output
    assert "=== technician_id=10010 technician_name=Petr ===" in output
    assert "blocked: no warehouse delta for reconciliation window" in output
    assert "[summary]" in output
    assert "technician_id" in output
    assert "10010" in output
    assert "processed=2 succeeded=1 blocked=1 skipped=0" in output


def test_batch_exit_code_zero_only_when_all_ok() -> None:
    ok_only = PreviewAllTechniciansResult(
        outcomes=(
            TechnicianPreviewOutcome(
                technician_id=TechnicianId("10003"),
                technician_name="Ivan",
                status="ok",
                reason="",
                preview=_minimal_preview(),
            ),
        ),
    )
    with_blocked = PreviewAllTechniciansResult(
        outcomes=(
            TechnicianPreviewOutcome(
                technician_id=TechnicianId("10003"),
                technician_name="Ivan",
                status="skipped",
                reason="nothing to reconcile in window",
                preview=None,
            ),
        ),
    )
    assert batch_exit_code(ok_only) == 0
    assert batch_exit_code(with_blocked) == 1
