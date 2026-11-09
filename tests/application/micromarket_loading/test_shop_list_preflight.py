from __future__ import annotations

from decimal import Decimal

from src.application.micromarket_loading.shop_list_preflight import (
    GroupCandidate,
    LocationCandidate,
    PreflightError,
    PreflightOk,
    ProductCandidate,
    PublishSnapshotLine,
    ShopCandidate,
    prepare_shop_list_write,
)


class _Spy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add_category(self, *, template_id: int, category_id: int) -> None:
        self.calls.append("category")

    def remove_product(self, *, template_id: int, product_id: int) -> None:
        self.calls.append("remove")

    def add_product(
        self,
        *,
        template_id: int,
        product_id: int,
        price_rub: Decimal,
        category_id: int,
        location_id: int,
    ) -> None:
        self.calls.append("add")

    def add_command(self, *, shop_id: int) -> None:
        self.calls.append("command")


def test_preflight_missing_showcase_does_not_write() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20408, 1),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Нужна одна витрина"
    assert spy.calls == []


def test_preflight_duplicate_live_product_does_not_write() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(
            ProductCandidate(167925, "PROBE01", False),
            ProductCandidate(167999, "PROBE01", False),
        ),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Товар PROBE01 не найден в Kit Shop"
    assert spy.calls == []


def test_preflight_zero_shops() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Магазин Kit Shop для этого аппарата не найден"
    assert spy.calls == []


def test_preflight_two_shops() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(
            ShopCandidate(1, "PROBE микромаркет [799]", 7140),
            ShopCandidate(2, "PROBE2 микромаркет [799]", 7141),
        ),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Магазин Kit Shop для этого аппарата не найден"
    assert spy.calls == []


def test_preflight_missing_template_id() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", None),),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "У магазина нет шаблона матрицы"
    assert spy.calls == []


def test_preflight_two_type2_locations() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(
            LocationCandidate(20409, 2),
            LocationCandidate(20410, 2),
        ),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Нужна одна витрина"
    assert spy.calls == []


def test_preflight_deleted_card_is_not_live() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(165454, "PROBE01", True),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Товар PROBE01 не найден в Kit Shop"
    assert spy.calls == []


def test_preflight_missing_group() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Группа товара PROBE01 не найдена в Kit Shop"
    assert spy.calls == []


def test_preflight_empty_lines_ok() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(),
        groups=(),
        lines=(),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.rows == ()
    assert result.shop_id == 1
    assert result.template_id == 7140
    assert result.location_id == 20409
    assert spy.calls == []


def test_preflight_picks_matching_shop_among_others() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(
            ShopCandidate(9, "Другая точка [701]", 100),
            ShopCandidate(1, "PROBE микромаркет [799]", 7140),
            ShopCandidate(8, "Ещё точка [702]", 200),
        ),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.shop_id == 1
    assert result.template_id == 7140
    assert spy.calls == []


def test_preflight_type1_plus_one_showcase_ok() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(
            LocationCandidate(20408, 1),
            LocationCandidate(20409, 2),
        ),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.location_id == 20409
    assert result.rows[0].location_id == 20409
    assert spy.calls == []


def test_preflight_ok_builds_desired_row() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(
            ProductCandidate(167925, "PROBE01", False),
            ProductCandidate(165454, "PROBE01", True),
        ),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.shop_id == 1
    assert result.template_id == 7140
    assert result.location_id == 20409
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.product_id == 167925
    assert row.price_rub == Decimal("151")
    assert row.category_id == 6348
    assert row.location_id == 20409
    assert row.disabled is False
    assert spy.calls == []


def test_preflight_propagates_disabled_true_to_desired_row() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "PROBE01", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("PROBE01", Decimal("151"), 6348, True),),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.rows[0].disabled is True
    assert spy.calls == []


def test_preflight_matches_vendor_code_to_domain_number() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(
            ProductCandidate(167925, "d-1", False),
            ProductCandidate(167926, "2311", False),
        ),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("d-1", Decimal("15"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightOk)
    assert result.rows[0].product_id == 167925
    assert spy.calls == []


def test_preflight_domain_number_does_not_match_catalog_vendor_code() -> None:
    spy = _Spy()
    result = prepare_shop_list_write(
        machine_code="799",
        shops=(ShopCandidate(1, "PROBE микромаркет [799]", 7140),),
        locations=(LocationCandidate(20409, 2),),
        products=(ProductCandidate(167925, "2311", False),),
        groups=(GroupCandidate(6348),),
        lines=(PublishSnapshotLine("d-1", Decimal("15"), 6348),),
        writer=spy,
    )
    assert isinstance(result, PreflightError)
    assert result.message == "Товар d-1 не найден в Kit Shop"
    assert spy.calls == []
