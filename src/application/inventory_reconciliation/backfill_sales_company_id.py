from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.ports import MachineSalesStore


@beartype
@dataclass(frozen=True, slots=True)
class BackfillSalesCompanyIdResult:
    patched: int
    skipped_no_kit_id: int
    skipped_unresolved: int


@beartype
def backfill_sales_company_id(
    *,
    sales_store: MachineSalesStore,
    resolve_mk_company_id: Callable[[int], int | None],
) -> BackfillSalesCompanyIdResult:
    patched = 0
    skipped_no_kit_id = 0
    skipped_unresolved = 0
    for sale in sales_store.list_with_missing_company_id():
        kit_company_id = sale.kit_vending_company_id
        if kit_company_id is None:
            skipped_no_kit_id += 1
            continue
        mk_company_id = resolve_mk_company_id(kit_company_id)
        if mk_company_id is None:
            skipped_unresolved += 1
            continue
        if sales_store.patch_company_id_if_missing(sale.source_id, mk_company_id):
            patched += 1
    return BackfillSalesCompanyIdResult(
        patched=patched,
        skipped_no_kit_id=skipped_no_kit_id,
        skipped_unresolved=skipped_unresolved,
    )
