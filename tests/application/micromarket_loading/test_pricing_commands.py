from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.micromarket_loading.pricing_commands import (
    RecalcMicromarketCalculatedPrices,
    ResetMicromarketPlanogramLinePrice,
    ResetMicromarketPlanogramPrices,
    SaveMicromarketPricingRules,
    UpsertMicromarketProductMultiplier,
    preview_calculated_sell_for_line,
)
from src.application.micromarket_loading.pricing_stores import (
    InMemoryMicromarketMachineMultiplierStore,
    InMemoryMicromarketPriceChangeJournal,
    InMemoryMicromarketPricingRulesStore,
    InMemoryMicromarketProductMultiplierStore,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.domain.micromarket_pricing.bounds import ProductMultiplierBounds
from src.domain.micromarket_pricing.errors import MultiplierOutOfBounds
from src.domain.micromarket_pricing.formula import MicromarketPricingRules
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketPlanogramStore,
)


@dataclass(slots=True)
class _MirrorStore:
    _by_code: dict[str, ProcurementMirror] = field(default_factory=dict)

    def get(self, catalog_code: str) -> ProcurementMirror | None:
        return self._by_code.get(catalog_code)

    def upsert(self, mirror: ProcurementMirror) -> None:
        self._by_code[mirror.catalog_code] = mirror

    def delete(self, catalog_code: str) -> None:
        self._by_code.pop(catalog_code, None)

    def codes(self) -> tuple[str, ...]:
        return tuple(self._by_code)


def _shelf() -> tuple[MicromarketPlanogramShelf, ...]:
    return (MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),)


def _rules() -> MicromarketPricingRules:
    return MicromarketPricingRules(
        margin_percent=Decimal("50"),
        margin_floor=Decimal("20"),
        rounding_last_digits=None,
    )


def _mirror(code: str, price: str) -> ProcurementMirror:
    return ProcurementMirror(
        catalog_code=code,
        supplier_id=None,
        supplier_name=None,
        last_buy_price=Decimal(price),
        supply_moment=None,
        synced_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def _line(
    *,
    code: str = "2311",
    price: str = "100",
    origin: str = "calculated",
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=code,
        target_qty=1,
        price_rub=Decimal(price),
        active=True,
        sort_order=0,
        kit_group_id=6348,
        price_origin=origin,  # type: ignore[arg-type]
    )


def test_preview_calculated_sell_for_line() -> None:
    mirrors = _MirrorStore({"2311": _mirror("2311", "100")})
    product_mult = InMemoryMicromarketProductMultiplierStore()
    product_mult.upsert("2311", Decimal("1.2"))
    machine_mult = InMemoryMicromarketMachineMultiplierStore()
    machine_mult.upsert("701", Decimal("1.5"))
    # P=100, margin=max(50,20)=50 → base=150 → 150*1.2*1.5=270
    sell = preview_calculated_sell_for_line(
        line=_line(code="2311", price="999", origin="manual"),
        machine_code="701",
        rules=_rules(),
        product_multipliers=product_mult,
        machine_multipliers=machine_mult,
        mirrors=mirrors,
        products=None,
    )
    assert sell == 270
    assert (
        preview_calculated_sell_for_line(
            line=_line(code="2311", price="999", origin="manual"),
            machine_code="701",
            rules=None,
            product_multipliers=product_mult,
            machine_multipliers=machine_mult,
            mirrors=mirrors,
            products=None,
        )
        is None
    )


def test_preview_uses_domain_product_multiplier_over_catalog() -> None:
    mirrors = _MirrorStore({"2311": _mirror("2311", "100")})
    product_mult = InMemoryMicromarketProductMultiplierStore()
    product_mult.upsert("2311", Decimal("1.2"))
    product_mult.upsert("dp-water", Decimal("2.0"))
    machine_mult = InMemoryMicromarketMachineMultiplierStore()
    line = MicromarketPlanogramLine(
        product_code="2311",
        target_qty=1,
        price_rub=Decimal("999"),
        active=True,
        sort_order=0,
        kit_group_id=6348,
        price_origin="manual",
        domain_product_id="dp-water",
    )
    # P=100, margin=50 → 150 * 2.0 * 1 = 300 (domain mult, not catalog 1.2)
    sell = preview_calculated_sell_for_line(
        line=line,
        machine_code="701",
        rules=_rules(),
        product_multipliers=product_mult,
        machine_multipliers=machine_mult,
        mirrors=mirrors,
        products=None,
    )
    assert sell == 300


def test_recalc_updates_calculated_only() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _line(code="2311", price="100", origin="calculated"),
                _line(code="2312", price="200", origin="manual"),
            ),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    mirrors = _MirrorStore(
        {
            "2311": _mirror("2311", "100"),
            "2312": _mirror("2312", "100"),
        }
    )
    journal = InMemoryMicromarketPriceChangeJournal()
    RecalcMicromarketCalculatedPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=mirrors,
        journal=journal,
        max_price_delta_pct=Decimal("0"),
    ).execute()
    doc = store.get("701")
    assert doc is not None
    by_code = {line.product_code: line for line in doc.lines}
    # P=100, margin=max(50,20)=50 → sell=150
    assert by_code["2311"].price_rub == Decimal("150")
    assert by_code["2311"].price_origin == "calculated"
    assert by_code["2312"].price_rub == Decimal("200")
    assert by_code["2312"].price_origin == "manual"
    assert all(e.origin == "calculated" for e in journal._entries)


def test_recalc_skips_without_purchase() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="100", origin="calculated"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    RecalcMicromarketCalculatedPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore(),
        journal=InMemoryMicromarketPriceChangeJournal(),
        max_price_delta_pct=Decimal("0"),
    ).execute()
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("100")


def test_recalc_delta_decrease_keeps_previous() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="200", origin="calculated"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    RecalcMicromarketCalculatedPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=journal,
        max_price_delta_pct=Decimal("10"),
    ).execute()
    doc = store.get("701")
    assert doc is not None
    # sell would be 150; decrease from 200 is 25% > 10% → keep 200
    assert doc.lines[0].price_rub == Decimal("200")
    assert journal._entries[0].reason == "max_delta_decrease_exceeded"


def test_reset_line_applies_sell_and_journals_reset() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="100", origin="manual"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    result = ResetMicromarketPlanogramLinePrice(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=journal,
    ).execute(machine_code="701", product_code="2311")
    doc = store.get("701")
    assert doc is not None
    assert result.found is True
    assert result.applied is True
    assert result.delta_blocked is False
    assert doc.lines[0].price_rub == Decimal("150")
    assert doc.lines[0].price_origin == "calculated"
    assert journal._entries[0].origin == "reset"


def test_reset_line_matches_domain_product_id() -> None:
    # edge: admin reset form posts domain_product_id when legacy product_code empty
    from dataclasses import replace

    from tests.application.product_identity.fakes import FakeDomainProductStore

    from src.application.product_identity import DomainProduct

    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="pid-bona",
            number="d-1",
            name="BonaAqua",
            catalog_code="2311",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                replace(
                    _line(code="", price="100", origin="manual"),
                    domain_product_id="pid-bona",
                ),
            ),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    result = ResetMicromarketPlanogramLinePrice(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=journal,
        products=products,
    ).execute(machine_code="701", product_code="pid-bona")
    doc = store.get("701")
    assert doc is not None
    assert result.found is True
    assert result.applied is True
    assert doc.lines[0].price_origin == "calculated"
    assert doc.lines[0].price_rub == Decimal("150")


def test_reset_line_applies_despite_large_decrease() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="200", origin="manual"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    result = ResetMicromarketPlanogramLinePrice(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=journal,
    ).execute(machine_code="701", product_code="2311")
    doc = store.get("701")
    assert doc is not None
    # sell=150; decrease from 200 is 25% — reset ignores MICROMARKET_MAX_PRICE_DELTA_PCT
    assert result.found is True
    assert result.applied is True
    assert result.delta_blocked is False
    assert doc.lines[0].price_rub == Decimal("150")
    assert doc.lines[0].price_origin == "calculated"
    assert journal._entries[0].origin == "reset"
    assert journal._entries[0].reason is None


def test_reset_all_applies_despite_large_decrease() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(code="2311", price="200", origin="manual"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    result = ResetMicromarketPlanogramPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=journal,
    ).execute(machine_code="701")
    doc = store.get("701")
    assert doc is not None
    assert result.applied_count == 1
    assert result.delta_blocked_count == 0
    assert doc.lines[0].price_rub == Decimal("150")
    assert doc.lines[0].price_origin == "calculated"
    assert journal._entries[0].reason is None


def test_reset_all_applies_system_path() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _line(code="2311", price="100", origin="manual"),
                _line(code="2312", price="100", origin="manual"),
            ),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    journal = InMemoryMicromarketPriceChangeJournal()
    result = ResetMicromarketPlanogramPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore(
            {
                "2311": _mirror("2311", "100"),
                "2312": _mirror("2312", "100"),
            }
        ),
        journal=journal,
    ).execute(machine_code="701")
    doc = store.get("701")
    assert doc is not None
    assert result.applied_count == 2
    assert result.delta_blocked_count == 0
    assert all(line.price_origin == "calculated" for line in doc.lines)
    assert all(line.price_rub == Decimal("150") for line in doc.lines)
    assert len(journal._entries) == 2
    assert {e.origin for e in journal._entries} == {"reset"}


def test_reset_line_opens_publish_when_price_changes() -> None:
    """happy: reset that changes price_rub marks shop list unpublished (ISS-471)."""
    from dataclasses import replace

    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        replace(
            MicromarketPlanogram(
                machine_code="701",
                lines=(_line(price="100", origin="manual"),),
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                shelves=_shelf(),
            ),
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="pub-1",
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    ResetMicromarketPlanogramLinePrice(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=InMemoryMicromarketPriceChangeJournal(),
    ).execute(machine_code="701", product_code="2311")
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("150")
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_publication_id == ""


def test_reset_line_keeps_status_when_price_unchanged() -> None:
    """happy: no-op reset does not reopen Publish (ISS-471)."""
    from dataclasses import replace

    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        replace(
            MicromarketPlanogram(
                machine_code="701",
                lines=(_line(price="150", origin="calculated"),),
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                shelves=_shelf(),
            ),
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="pub-1",
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    ResetMicromarketPlanogramLinePrice(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=InMemoryMicromarketPriceChangeJournal(),
    ).execute(machine_code="701", product_code="2311")
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("150")
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert doc.shop_list_publication_id == "pub-1"


def test_reset_all_opens_publish_when_price_changes() -> None:
    from dataclasses import replace

    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        replace(
            MicromarketPlanogram(
                machine_code="701",
                lines=(_line(price="100", origin="manual"),),
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                shelves=_shelf(),
            ),
            shop_list_status=ShopListPublishStatus.PUBLISHED,
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    rules_store.save(_rules())
    ResetMicromarketPlanogramPrices(
        planograms=store,
        rules_store=rules_store,
        product_multipliers=InMemoryMicromarketProductMultiplierStore(),
        machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
        mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
        journal=InMemoryMicromarketPriceChangeJournal(),
    ).execute(machine_code="701")
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED


def test_save_rules_triggers_recalc() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(price="100", origin="calculated"),),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            shelves=_shelf(),
        ),
    )
    rules_store = InMemoryMicromarketPricingRulesStore()
    SaveMicromarketPricingRules(
        rules_store=rules_store,
        recalc=RecalcMicromarketCalculatedPrices(
            planograms=store,
            rules_store=rules_store,
            product_multipliers=InMemoryMicromarketProductMultiplierStore(),
            machine_multipliers=InMemoryMicromarketMachineMultiplierStore(),
            mirrors=_MirrorStore({"2311": _mirror("2311", "100")}),
            journal=InMemoryMicromarketPriceChangeJournal(),
            max_price_delta_pct=Decimal("0"),
        ),
    ).execute(_rules())
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("150")
    assert rules_store.get() == _rules()


def test_upsert_product_multiplier_rejects_out_of_bounds() -> None:
    cmd = UpsertMicromarketProductMultiplier(
        store=InMemoryMicromarketProductMultiplierStore(),
        bounds=ProductMultiplierBounds(min=Decimal("0.8"), max=Decimal("3")),
        recalc=None,
    )
    result = cmd.execute(product_code="2311", multiplier=Decimal("5"))
    assert result.is_err
    assert isinstance(result.error, MultiplierOutOfBounds)
