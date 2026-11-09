from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs

from beartype import beartype
from starlette.responses import RedirectResponse, Response

from src.application.micromarket_loading import (
    RecalcMicromarketCalculatedPrices,
    SaveMicromarketPricingRules,
    UpsertMicromarketMachineMultiplier,
    UpsertMicromarketProductMultiplier,
)
from src.application.product_identity import catalog_codes_of
from src.domain.micromarket_pricing.bounds import (
    MachineMultiplierBounds,
    ProductMultiplierBounds,
)
from src.domain.micromarket_pricing.formula import MicromarketPricingRules
from src.domain.system_user import AdminPanel
from src.interfaces.admin.clock_display import format_admin_moment
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import _user_may_access_admin
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.planogram_product_options import planogram_product_options

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPricesTabContext:
    can_edit: bool
    margin_percent: str
    margin_floor: str
    rounding_last_digits: str
    product_rows: tuple[tuple[str, str, str], ...]
    machine_rows: tuple[tuple[str, str, str], ...]
    journal_rows: tuple[dict[str, str], ...]
    product_options_json: str
    error: str | None = None


@beartype
def can_edit_micromarket_prices(deps: AdminHttpDeps, telegram_user_id: int) -> bool:
    return _user_may_access_admin(deps, telegram_user_id, AdminPanel.MATRIX_PRICING)


@beartype
def build_prices_tab_context(
    deps: AdminHttpDeps,
    *,
    telegram_user_id: int,
    error: str | None = None,
) -> MicromarketPricesTabContext:
    rules_store = deps.micromarket_pricing_rules_store
    rules = rules_store.get() if rules_store is not None else None
    product_store = deps.micromarket_product_multiplier_store
    machine_store = deps.micromarket_machine_multiplier_store
    journal = deps.micromarket_price_change_journal
    products = deps.domain_product_store
    product_rows: list[tuple[str, str, str]] = []
    if product_store is not None:
        for key, mult in sorted(product_store.list_all().items()):
            domain_id = key
            name = key
            if products is not None:
                product = products.get(key)
                if product is None:
                    product = products.get_by_catalog_code(key)
                if product is not None:
                    domain_id = product.domain_product_id
                    name = product.name
            product_rows.append((domain_id, name, str(mult)))
    machine_rows: list[tuple[str, str, str]] = []
    if machine_store is not None and deps.master_stores is not None:
        from src.application.master_data import MachineKind

        stores = deps.master_stores
        by_id = machine_store.list_all()
        for machine in stores.machines.list_all():
            if machine.kind is not MachineKind.MICRO_MARKET:
                continue
            mid = machine.machine_id.value
            mult_val: Decimal | None = by_id.get(mid)
            name = machine_profile_display_name(stores, machine)
            machine_rows.append((mid, name, "" if mult_val is None else str(mult_val)))
    journal_rows: list[dict[str, str]] = []
    if journal is not None:
        planograms = deps.micromarket_planogram_store
        machine_ids: list[str] = []
        if planograms is not None:
            machine_ids = [doc.machine_code for doc in planograms.list_all()]
        entries: list[Any] = []
        for mid in machine_ids[:20]:
            entries.extend(journal.list_for_machine(mid, limit=20))
        entries.sort(key=lambda e: e.at, reverse=True)
        machine_name_by_id = {mid: name for mid, name, _mult in machine_rows}
        for entry in entries[:50]:
            product_label = entry.product_code
            if products is not None:
                product = products.get(entry.product_code)
                if product is None:
                    product = products.get_by_catalog_code(entry.product_code)
                if product is not None:
                    product_label = product.name
            at_display = format_admin_moment(entry.at, deps.timezone)
            journal_rows.append(
                {
                    "at": at_display,
                    "at_day": at_display.split(" ", 1)[0] if at_display != "—" else "",
                    "machine_id": entry.machine_id,
                    "machine_name": machine_name_by_id.get(entry.machine_id, entry.machine_id),
                    "product_name": product_label,
                    "old": "" if entry.old_price_rub is None else str(entry.old_price_rub),
                    "new": str(entry.new_price_rub),
                    "origin": entry.origin,
                    "reason": entry.reason or "",
                }
            )
    rounding = ""
    if rules is not None and rules.rounding_last_digits is not None:
        rounding = ",".join(str(d) for d in sorted(rules.rounding_last_digits))
    options_json = "[]"
    if products is not None:
        options = planogram_product_options(products)
        options_json = json.dumps(
            [
                {
                    "domain_product_id": item.domain_product_id,
                    "name": item.name,
                    "number": item.number,
                    "linked": item.linked,
                }
                for item in options
            ],
            ensure_ascii=False,
        )
    return MicromarketPricesTabContext(
        can_edit=can_edit_micromarket_prices(deps, telegram_user_id),
        margin_percent="" if rules is None else str(rules.margin_percent),
        margin_floor="" if rules is None else str(rules.margin_floor),
        rounding_last_digits=rounding,
        product_rows=tuple(product_rows),
        machine_rows=tuple(machine_rows),
        journal_rows=tuple(journal_rows),
        product_options_json=options_json,
        error=error,
    )


@beartype
def prices_tab_template_vars(ctx: MicromarketPricesTabContext) -> dict[str, Any]:
    return {
        "prices_can_edit": ctx.can_edit,
        "prices_margin_percent": ctx.margin_percent,
        "prices_margin_floor": ctx.margin_floor,
        "prices_rounding_last_digits": ctx.rounding_last_digits,
        "prices_product_rows": ctx.product_rows,
        "prices_machine_rows": ctx.machine_rows,
        "prices_journal_rows": ctx.journal_rows,
        "prices_error": ctx.error,
        "prices_margin_percent_min": None,
        "prices_product_options_json": ctx.product_options_json,
    }


@beartype
def save_micromarket_prices_from_form(
    deps: AdminHttpDeps,
    *,
    body: bytes,
) -> str | None:
    """Return RU error message or None on success."""
    rules_store = deps.micromarket_pricing_rules_store
    product_store = deps.micromarket_product_multiplier_store
    machine_store = deps.micromarket_machine_multiplier_store
    journal = deps.micromarket_price_change_journal
    planograms = deps.micromarket_planogram_store
    mirrors = deps.procurement_mirror_store
    products = deps.domain_product_store
    if (
        rules_store is None
        or product_store is None
        or machine_store is None
        or journal is None
        or planograms is None
    ):
        return "Ценовое ядро не подключено"
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    try:
        margin_percent = Decimal((parsed.get("margin_percent") or [""])[0].strip())
        margin_floor = Decimal((parsed.get("margin_floor") or [""])[0].strip())
    except InvalidOperation, ValueError:
        return "Некорректные % или пол наценки"
    if not (
        deps.micromarket_margin_percent_min <= margin_percent <= deps.micromarket_margin_percent_max
    ):
        return "Процент наценки вне допустимого диапазона"
    if not (deps.micromarket_margin_floor_min <= margin_floor <= deps.micromarket_margin_floor_max):
        return "Минимальная наценка вне допустимого диапазона"
    rounding_raw = (parsed.get("rounding_last_digits") or [""])[0].strip()
    rounding: frozenset[int] | None
    if not rounding_raw:
        rounding = None
    else:
        try:
            rounding = frozenset(
                int(part.strip()) for part in rounding_raw.split(",") if part.strip()
            )
        except ValueError:
            return "Некорректный rounding_last_digits"
    from src.application.micromarket_loading import EmptyProcurementMirrorStore

    mirrors_port = mirrors if mirrors is not None else EmptyProcurementMirrorStore()
    recalc = RecalcMicromarketCalculatedPrices(
        planograms=planograms,
        rules_store=rules_store,
        product_multipliers=product_store,
        machine_multipliers=machine_store,
        mirrors=mirrors_port,
        journal=journal,
        max_price_delta_pct=deps.micromarket_max_price_delta_pct,
        products=deps.domain_product_store,
    )
    SaveMicromarketPricingRules(rules_store=rules_store, recalc=None).execute(
        MicromarketPricingRules(
            margin_percent=margin_percent,
            margin_floor=margin_floor,
            rounding_last_digits=rounding,
        )
    )
    product_bounds = ProductMultiplierBounds(
        min=deps.micromarket_product_multiplier_min,
        max=deps.micromarket_product_multiplier_max,
    )
    machine_bounds = MachineMultiplierBounds(
        min=deps.micromarket_machine_multiplier_min,
        max=deps.micromarket_machine_multiplier_max,
    )
    product_ids = parsed.get("product_domain_id", [])
    product_mults = parsed.get("product_multiplier", [])
    for domain_id, mult_raw in zip(product_ids, product_mults, strict=False):
        domain_id = domain_id.strip()
        mult_raw = mult_raw.strip()
        if not domain_id:
            continue
        if products is not None and products.get(domain_id) is None:
            return f"Неизвестный доменный товар {domain_id}"
        if not mult_raw:
            product_store.delete(domain_id)
            continue
        try:
            mult = Decimal(mult_raw)
        except InvalidOperation, ValueError:
            return f"Некорректный множитель товара {domain_id}"
        result = UpsertMicromarketProductMultiplier(
            store=product_store,
            bounds=product_bounds,
            recalc=None,
        ).execute(product_code=domain_id, multiplier=mult)
        if result.is_err():
            return f"Множитель товара {domain_id} вне границ"
        if products is not None:
            product = products.get(domain_id)
            if product is not None:
                for code in catalog_codes_of(product):
                    if code != domain_id:
                        product_store.delete(code)
    machine_ids = parsed.get("machine_id", [])
    machine_mults = parsed.get("machine_multiplier", [])
    for mid, mult_raw in zip(machine_ids, machine_mults, strict=False):
        mid = mid.strip()
        mult_raw = mult_raw.strip()
        if not mid or not mult_raw:
            continue
        try:
            mult = Decimal(mult_raw)
        except InvalidOperation, ValueError:
            return f"Некорректный множитель аппарата {mid}"
        result = UpsertMicromarketMachineMultiplier(
            store=machine_store,
            bounds=machine_bounds,
            recalc=None,
        ).execute(machine_id=mid, multiplier=mult)
        if result.is_err():
            return f"Множитель аппарата {mid} вне границ"
    applied = recalc.execute()
    _LOGGER.info("micromarket_prices_saved", extra={"recalc_applied": applied})
    return None


@beartype
def redirect_prices(*, error: str | None = None) -> Response:
    if error:
        from urllib.parse import quote

        return RedirectResponse(
            f"/admin/micromarket-planograms?tab=prices&prices_error={quote(error)}",
            status_code=303,
        )
    return RedirectResponse("/admin/micromarket-planograms?tab=prices", status_code=303)
