from __future__ import annotations

from decimal import Decimal

from src.application.micromarket_loading.template_sync import (
    DesiredTemplateRow,
    TemplateRow,
    plan_kit_shop_template_sync,
)


def test_sync_plan_leaves_matching_row() -> None:
    desired = DesiredTemplateRow(10, Decimal("151"), 6348, 20409)
    current = TemplateRow(10, Decimal("151"), 6348, 20409, False)
    plan = plan_kit_shop_template_sync(
        desired=(desired,),
        current=(current,),
        category_ids_on_template=(6348, 0),
    )
    assert plan.add_category_ids == ()
    assert plan.remove_product_ids == ()
    assert plan.add_rows == ()


def test_sync_plan_price_change_removes_then_adds() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("152"), 6348, 20409),),
        current=(TemplateRow(10, Decimal("151"), 6348, 20409, False),),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == (10,)
    assert plan.add_rows == (DesiredTemplateRow(10, Decimal("152"), 6348, 20409),)


def test_sync_plan_removes_extra_product() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6348, 20409),),
        current=(
            TemplateRow(10, Decimal("151"), 6348, 20409, False),
            TemplateRow(11, Decimal("1"), 6348, 20409, False),
        ),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == (11,)
    assert plan.add_rows == ()


def test_sync_plan_moves_type1_location_to_type2() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6348, 20409),),
        current=(TemplateRow(10, Decimal("151"), 6348, 1, False),),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == (10,)
    assert plan.add_rows[0].location_id == 20409


def test_sync_plan_disabled_row_is_replaced() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6348, 20409),),
        current=(TemplateRow(10, Decimal("151"), 6348, 20409, True),),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == (10,)
    assert plan.add_rows == (DesiredTemplateRow(10, Decimal("151"), 6348, 20409),)


def test_sync_plan_adds_missing_category_and_keeps_extra() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6349, 20409),),
        current=(),
        category_ids_on_template=(0, 6348),
    )
    assert plan.add_category_ids == (6349,)
    assert 0 not in plan.remove_product_ids
    assert plan.add_rows == (DesiredTemplateRow(10, Decimal("151"), 6349, 20409),)


def test_sync_plan_keeps_extra_categories() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(),
        current=(),
        category_ids_on_template=(0, 6348),
    )
    assert plan.add_category_ids == ()
    assert plan.remove_product_ids == ()


def test_sync_plan_empty_desired_removes_all() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(),
        current=(
            TemplateRow(10, Decimal("1"), 6348, 20409, False),
            TemplateRow(11, Decimal("2"), 6349, 20409, False),
        ),
        category_ids_on_template=(6348, 6349, 0),
    )
    assert plan.remove_product_ids == (10, 11)
    assert plan.add_rows == ()
    assert plan.add_category_ids == ()


def test_sync_plan_desired_disabled_mismatch_rewrites() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6348, 20409, True),),
        current=(TemplateRow(10, Decimal("151"), 6348, 20409, False),),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == (10,)
    assert plan.add_rows == (DesiredTemplateRow(10, Decimal("151"), 6348, 20409, True),)


def test_sync_plan_matching_disabled_true_leaves_row() -> None:
    plan = plan_kit_shop_template_sync(
        desired=(DesiredTemplateRow(10, Decimal("151"), 6348, 20409, True),),
        current=(TemplateRow(10, Decimal("151"), 6348, 20409, True),),
        category_ids_on_template=(6348,),
    )
    assert plan.remove_product_ids == ()
    assert plan.add_rows == ()
