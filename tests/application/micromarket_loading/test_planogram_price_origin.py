from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from src.application.micromarket_loading import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    SaveMicromarketPlanogram,
)
from src.application.micromarket_loading.pricing_cutover import (
    CutoverMicromarketPlanogramPrices,
)
from src.application.micromarket_loading.pricing_stores import (
    InMemoryMicromarketPriceChangeJournal,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketPlanogramStore,
)


def _shelf(*group_ids: int) -> tuple[MicromarketPlanogramShelf, ...]:
    return tuple(
        MicromarketPlanogramShelf(kit_group_id=group_id, sort_order=index)
        for index, group_id in enumerate(group_ids)
    )


def _line(
    *,
    code: str = "2311",
    price: str = "100",
    origin: Literal["manual", "calculated"] = "manual",
    qty: int = 1,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=code,
        target_qty=qty,
        price_rub=Decimal(price),
        active=True,
        sort_order=0,
        kit_group_id=6348,
        price_origin=origin,
    )


def test_cutover_marks_all_lines_manual_keeps_price_and_journals() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _line(code="2311", price="189", origin="calculated"),
                _line(code="2312", price="50", origin="manual"),
            ),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    journal = InMemoryMicromarketPriceChangeJournal()
    fixed_now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

    painted = CutoverMicromarketPlanogramPrices(
        store=store,
        journal=journal,
        now_factory=lambda: fixed_now,
        actor="cutover",
    ).execute()

    assert painted == 2
    doc = store.get("701")
    assert doc is not None
    assert all(line.price_origin == "manual" for line in doc.lines)
    assert {line.product_code: line.price_rub for line in doc.lines} == {
        "2311": Decimal("189"),
        "2312": Decimal("50"),
    }
    assert len(journal._entries) == 2
    assert {e.origin for e in journal._entries} == {"cutover"}
    assert {e.new_price_rub for e in journal._entries} == {Decimal("189"), Decimal("50")}
    assert all(e.old_price_rub == e.new_price_rub for e in journal._entries)


def test_save_price_edit_sets_manual() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="100", origin="calculated"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(6348),
        ),
    )
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        machine_code="701",
        shelves=_shelf(6348),
        lines=[_line(price="120", origin="calculated")],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("120")
    assert doc.lines[0].price_origin == "manual"


def test_save_unrelated_field_keeps_calculated() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="100", origin="calculated", qty=1),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(6348),
        ),
    )
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        machine_code="701",
        shelves=_shelf(6348),
        lines=[_line(price="100", origin="manual", qty=5)],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].target_qty == 5
    assert doc.lines[0].price_rub == Decimal("100")
    assert doc.lines[0].price_origin == "calculated"
