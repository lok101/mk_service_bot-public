from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.ms_catalog_code import (
    planogram_line_ms_catalog_codes,
    resolve_planogram_line_ms_catalog_code,
)
from src.application.micromarket_loading.planogram import MicromarketPlanogramLine
from src.application.micromarket_loading.ports import (
    MicromarketMachineMultiplierStore,
    MicromarketPlanogramStore,
    MicromarketPriceChangeJournal,
    MicromarketPricingRulesStore,
    MicromarketProductMultiplierStore,
)
from src.application.micromarket_loading.pricing_stores import (
    MicromarketPriceChangeJournalEntry,
    PriceChangeOrigin,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.product_identity.ports import (
    DomainProductStore,
    ProcurementMirrorStore,
)
from src.domain.micromarket_pricing.bounds import (
    MachineMultiplierBounds,
    ProductMultiplierBounds,
    validate_multiplier,
)
from src.domain.micromarket_pricing.errors import MultiplierOutOfBounds
from src.domain.micromarket_pricing.formula import (
    MicromarketPricingRules,
    calculate_sell_price,
)
from src.domain.micromarket_pricing.merge import (
    CalculatedPriceOutcome,
    merge_calculated_price,
)
from src.domain.micromarket_pricing.result import Result


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketResetLineResult:
    found: bool
    applied: bool
    delta_blocked: bool


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketResetPricesResult:
    applied_count: int
    delta_blocked_count: int


@beartype
def _line_catalog_code(
    line: MicromarketPlanogramLine,
    *,
    products: DomainProductStore | None,
) -> str | None:
    domain_id = (line.domain_product_id or "").strip() or None
    return resolve_planogram_line_ms_catalog_code(
        products,
        product_code=line.product_code,
        domain_product_id=domain_id,
    )


@beartype
def _purchase_for_code(
    mirrors: ProcurementMirrorStore,
    catalog_code: str,
) -> Decimal | None:
    mirror = mirrors.get(catalog_code)
    if mirror is None or mirror.last_buy_price is None:
        return None
    return mirror.last_buy_price


@beartype
def _multiplier_or_one(store_value: Decimal | None) -> Decimal:
    return Decimal("1") if store_value is None else store_value


@beartype
def _product_multiplier_for_line(
    *,
    line: MicromarketPlanogramLine,
    product_multipliers: MicromarketProductMultiplierStore,
    products: DomainProductStore | None,
) -> Decimal:
    """Resolve product multiplier by domain id first, then legacy catalog codes."""
    domain_id = (line.domain_product_id or "").strip()
    if domain_id:
        by_domain = product_multipliers.get(domain_id)
        if by_domain is not None:
            return by_domain
    for code in planogram_line_ms_catalog_codes(
        products,
        product_code=line.product_code,
        domain_product_id=domain_id or None,
    ):
        by_code = product_multipliers.get(code)
        if by_code is not None:
            return by_code
    return Decimal("1")


@beartype
@dataclass(frozen=True, slots=True)
class _SystemPriceApply:
    new_price: Decimal
    reason: str | None
    journal_origin: PriceChangeOrigin
    outcome: CalculatedPriceOutcome


@beartype
def preview_calculated_sell_for_line(
    *,
    line: MicromarketPlanogramLine,
    machine_code: str,
    rules: MicromarketPricingRules | None,
    product_multipliers: MicromarketProductMultiplierStore,
    machine_multipliers: MicromarketMachineMultiplierStore,
    mirrors: ProcurementMirrorStore,
    products: DomainProductStore | None,
) -> int | None:
    """Pure formula sell for UI (no delta merge). None if no rules/purchase."""
    if rules is None:
        return None
    candidates = planogram_line_ms_catalog_codes(
        products,
        product_code=line.product_code,
        domain_product_id=(line.domain_product_id or "").strip() or None,
    )
    catalog_code: str | None = None
    purchase: Decimal | None = None
    for code in candidates:
        purchase = _purchase_for_code(mirrors, code)
        if purchase is not None:
            catalog_code = code
            break
    if catalog_code is None or purchase is None:
        return None
    return calculate_sell_price(
        purchase=purchase,
        product_multiplier=_product_multiplier_for_line(
            line=line,
            product_multipliers=product_multipliers,
            products=products,
        ),
        machine_multiplier=_multiplier_or_one(machine_multipliers.get(machine_code)),
        rules=rules,
    )


@beartype
def _system_sell_for_line(
    *,
    line: MicromarketPlanogramLine,
    machine_code: str,
    rules: MicromarketPricingRules,
    product_multipliers: MicromarketProductMultiplierStore,
    machine_multipliers: MicromarketMachineMultiplierStore,
    mirrors: ProcurementMirrorStore,
    products: DomainProductStore | None,
    max_price_delta_pct: Decimal,
    journal_origin: PriceChangeOrigin,
) -> _SystemPriceApply | None:
    sell_int = preview_calculated_sell_for_line(
        line=line,
        machine_code=machine_code,
        rules=rules,
        product_multipliers=product_multipliers,
        machine_multipliers=machine_multipliers,
        mirrors=mirrors,
        products=products,
    )
    if sell_int is None:
        return None
    sell = Decimal(sell_int)
    merged = merge_calculated_price(
        calculated_sell=sell,
        baseline_sell=line.price_rub,
        max_price_delta_pct=max_price_delta_pct,
    )
    return _SystemPriceApply(
        new_price=merged.deploy_price,
        reason=merged.reason,
        journal_origin=journal_origin,
        outcome=merged.outcome,
    )


@beartype
@dataclass(frozen=True, slots=True)
class RecalcMicromarketCalculatedPrices:
    planograms: MicromarketPlanogramStore
    rules_store: MicromarketPricingRulesStore
    product_multipliers: MicromarketProductMultiplierStore
    machine_multipliers: MicromarketMachineMultiplierStore
    mirrors: ProcurementMirrorStore
    journal: MicromarketPriceChangeJournal
    max_price_delta_pct: Decimal
    products: DomainProductStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)
    actor: str = "system"

    @beartype
    def execute(self) -> int:
        rules = self.rules_store.get()
        if rules is None:
            return 0
        updated = 0
        now = self.now_factory()
        for doc in self.planograms.list_all():
            changed = False
            new_lines: list[MicromarketPlanogramLine] = []
            for line in doc.lines:
                if line.price_origin != "calculated":
                    new_lines.append(line)
                    continue
                applied = _system_sell_for_line(
                    line=line,
                    machine_code=doc.machine_code,
                    rules=rules,
                    product_multipliers=self.product_multipliers,
                    machine_multipliers=self.machine_multipliers,
                    mirrors=self.mirrors,
                    products=self.products,
                    max_price_delta_pct=self.max_price_delta_pct,
                    journal_origin="calculated",
                )
                if applied is None:
                    new_lines.append(line)
                    continue
                catalog_code = _line_catalog_code(line, products=self.products) or ""
                if applied.new_price != line.price_rub or applied.reason is not None:
                    self.journal.append(
                        MicromarketPriceChangeJournalEntry(
                            machine_id=doc.machine_code,
                            product_code=catalog_code,
                            old_price_rub=line.price_rub,
                            new_price_rub=applied.new_price,
                            origin="calculated",
                            actor=self.actor,
                            reason=applied.reason,
                            at=now,
                        )
                    )
                if applied.new_price != line.price_rub:
                    changed = True
                    updated += 1
                    new_lines.append(
                        replace(
                            line,
                            price_rub=applied.new_price,
                            price_origin="calculated",
                        )
                    )
                else:
                    new_lines.append(line)
            if changed:
                self.planograms.upsert(replace(doc, lines=tuple(new_lines), updated_at=now))
        return updated


@beartype
@dataclass(frozen=True, slots=True)
class SaveMicromarketPricingRules:
    rules_store: MicromarketPricingRulesStore
    recalc: RecalcMicromarketCalculatedPrices | None = None

    @beartype
    def execute(self, rules: MicromarketPricingRules) -> None:
        self.rules_store.save(rules)
        if self.recalc is not None:
            self.recalc.execute()


@beartype
@dataclass(frozen=True, slots=True)
class UpsertMicromarketProductMultiplier:
    store: MicromarketProductMultiplierStore
    bounds: ProductMultiplierBounds
    recalc: RecalcMicromarketCalculatedPrices | None = None

    @beartype
    def execute(
        self, *, product_code: str, multiplier: Decimal
    ) -> Result[bool, MultiplierOutOfBounds]:
        outcome = validate_multiplier(multiplier, self.bounds)
        if outcome.is_err():
            return Result.err(outcome.error)
        self.store.upsert(product_code, outcome.value)
        if self.recalc is not None:
            self.recalc.execute()
        return Result.ok(True)


@beartype
@dataclass(frozen=True, slots=True)
class UpsertMicromarketMachineMultiplier:
    store: MicromarketMachineMultiplierStore
    bounds: MachineMultiplierBounds
    recalc: RecalcMicromarketCalculatedPrices | None = None

    @beartype
    def execute(
        self, *, machine_id: str, multiplier: Decimal
    ) -> Result[bool, MultiplierOutOfBounds]:
        outcome = validate_multiplier(multiplier, self.bounds)
        if outcome.is_err():
            return Result.err(outcome.error)
        self.store.upsert(machine_id, outcome.value)
        if self.recalc is not None:
            self.recalc.execute()
        return Result.ok(True)


@beartype
@dataclass(frozen=True, slots=True)
class ResetMicromarketPlanogramLinePrice:
    """Curator reset: always apply calculated sell (no MICROMARKET_MAX_PRICE_DELTA_PCT)."""

    planograms: MicromarketPlanogramStore
    rules_store: MicromarketPricingRulesStore
    product_multipliers: MicromarketProductMultiplierStore
    machine_multipliers: MicromarketMachineMultiplierStore
    mirrors: ProcurementMirrorStore
    journal: MicromarketPriceChangeJournal
    products: DomainProductStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)
    actor: str = "system"

    @beartype
    def execute(self, *, machine_code: str, product_code: str) -> MicromarketResetLineResult:
        rules = self.rules_store.get()
        if rules is None:
            return MicromarketResetLineResult(found=False, applied=False, delta_blocked=False)
        doc = self.planograms.get(machine_code)
        if doc is None:
            return MicromarketResetLineResult(found=False, applied=False, delta_blocked=False)
        target = product_code.strip()
        now = self.now_factory()
        new_lines: list[MicromarketPlanogramLine] = []
        found = False
        applied_ok = False
        changed = False
        price_changed = False
        for line in doc.lines:
            catalog = _line_catalog_code(line, products=self.products)
            identity = catalog or line.product_code.strip()
            domain_id = (line.domain_product_id or "").strip()
            if identity != target and line.product_code.strip() != target and domain_id != target:
                new_lines.append(line)
                continue
            found = True
            applied = _system_sell_for_line(
                line=line,
                machine_code=machine_code,
                rules=rules,
                product_multipliers=self.product_multipliers,
                machine_multipliers=self.machine_multipliers,
                mirrors=self.mirrors,
                products=self.products,
                max_price_delta_pct=Decimal("0"),
                journal_origin="reset",
            )
            if applied is None:
                new_lines.append(line)
                continue
            self.journal.append(
                MicromarketPriceChangeJournalEntry(
                    machine_id=machine_code,
                    product_code=catalog or target,
                    old_price_rub=line.price_rub,
                    new_price_rub=applied.new_price,
                    origin="reset",
                    actor=self.actor,
                    reason=applied.reason,
                    at=now,
                )
            )
            applied_ok = True
            changed = True
            if applied.new_price != line.price_rub:
                price_changed = True
            new_lines.append(
                replace(
                    line,
                    price_rub=applied.new_price,
                    price_origin="calculated",
                )
            )
        if not found:
            return MicromarketResetLineResult(found=False, applied=False, delta_blocked=False)
        if changed:
            updated = replace(doc, lines=tuple(new_lines), updated_at=now)
            if price_changed:
                updated = replace(
                    updated,
                    shop_list_status=ShopListPublishStatus.UNPUBLISHED,
                    shop_list_error="",
                    shop_list_publication_id="",
                    shop_list_catch_up_requested=False,
                )
            self.planograms.upsert(updated)
        return MicromarketResetLineResult(
            found=True,
            applied=applied_ok,
            delta_blocked=False,
        )


@beartype
@dataclass(frozen=True, slots=True)
class ResetMicromarketPlanogramPrices:
    """Curator reset-all: always apply calculated sell (no MICROMARKET_MAX_PRICE_DELTA_PCT)."""

    planograms: MicromarketPlanogramStore
    rules_store: MicromarketPricingRulesStore
    product_multipliers: MicromarketProductMultiplierStore
    machine_multipliers: MicromarketMachineMultiplierStore
    mirrors: ProcurementMirrorStore
    journal: MicromarketPriceChangeJournal
    products: DomainProductStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)
    actor: str = "system"

    @beartype
    def execute(self, *, machine_code: str) -> MicromarketResetPricesResult:
        rules = self.rules_store.get()
        if rules is None:
            return MicromarketResetPricesResult(applied_count=0, delta_blocked_count=0)
        doc = self.planograms.get(machine_code)
        if doc is None or not doc.lines:
            return MicromarketResetPricesResult(applied_count=0, delta_blocked_count=0)
        now = self.now_factory()
        new_lines: list[MicromarketPlanogramLine] = []
        applied_count = 0
        price_changed = False
        for line in doc.lines:
            applied = _system_sell_for_line(
                line=line,
                machine_code=machine_code,
                rules=rules,
                product_multipliers=self.product_multipliers,
                machine_multipliers=self.machine_multipliers,
                mirrors=self.mirrors,
                products=self.products,
                max_price_delta_pct=Decimal("0"),
                journal_origin="reset",
            )
            if applied is None:
                new_lines.append(line)
                continue
            catalog = _line_catalog_code(line, products=self.products) or line.product_code
            self.journal.append(
                MicromarketPriceChangeJournalEntry(
                    machine_id=machine_code,
                    product_code=catalog,
                    old_price_rub=line.price_rub,
                    new_price_rub=applied.new_price,
                    origin="reset",
                    actor=self.actor,
                    reason=applied.reason,
                    at=now,
                )
            )
            if applied.new_price != line.price_rub:
                price_changed = True
            new_lines.append(
                replace(
                    line,
                    price_rub=applied.new_price,
                    price_origin="calculated",
                )
            )
            applied_count += 1
        if applied_count:
            updated = replace(doc, lines=tuple(new_lines), updated_at=now)
            if price_changed:
                updated = replace(
                    updated,
                    shop_list_status=ShopListPublishStatus.UNPUBLISHED,
                    shop_list_error="",
                    shop_list_publication_id="",
                    shop_list_catch_up_requested=False,
                )
            self.planograms.upsert(updated)
        return MicromarketResetPricesResult(
            applied_count=applied_count,
            delta_blocked_count=0,
        )
