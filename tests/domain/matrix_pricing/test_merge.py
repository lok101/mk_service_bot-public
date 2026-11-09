from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.merge import SnapshotLine, merge_sku_price


def _snapshot(*, code: str = "ABC", price: str = "100") -> SnapshotLine:
    return SnapshotLine(
        product_code=code,
        product_name="Item",
        deploy_price=Decimal(price),
        capacity=10,
    )


def test_first_run_applied_on_validation_pass() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("50"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=None,
        is_first_run=True,
        has_baseline_line=False,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "applied"
    assert result.deploy_price == Decimal("50")


def test_first_run_skipped_on_validation_fail() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("50"),
        purchase_valid=False,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=None,
        is_first_run=True,
        has_baseline_line=False,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "skipped_no_baseline"


def test_strong_decrease_kept_previous() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("65"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=_snapshot(price="100"),
        is_first_run=False,
        has_baseline_line=True,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "kept_previous"
    assert result.reason == "max_delta_decrease_exceeded"


def test_strong_increase_applied_with_flag() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("140"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=_snapshot(price="100"),
        is_first_run=False,
        has_baseline_line=True,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "applied"
    assert result.strong_price_increase is True


def test_product_change_delta_off_applied_on_pass() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("80"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="NEW",
        snapshot=_snapshot(code="OLD"),
        is_first_run=False,
        has_baseline_line=True,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "applied"


def test_product_change_fail_no_fallback() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("80"),
        purchase_valid=False,
        capacity_valid=True,
        catalog_product_code="NEW",
        snapshot=_snapshot(code="OLD"),
        is_first_run=False,
        has_baseline_line=True,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "skipped_no_baseline"


def test_zero_delta_threshold_disables_freeze() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("50"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=_snapshot(price="100"),
        is_first_run=False,
        has_baseline_line=True,
        max_price_delta_pct=Decimal("0"),
    )
    assert result.outcome == "applied"


def test_new_line_in_existing_matrix_behaves_like_local_first_run() -> None:
    result = merge_sku_price(
        calculated_sell=Decimal("55"),
        purchase_valid=True,
        capacity_valid=True,
        catalog_product_code="ABC",
        snapshot=None,
        is_first_run=False,
        has_baseline_line=False,
        max_price_delta_pct=Decimal("30"),
    )
    assert result.outcome == "applied"
