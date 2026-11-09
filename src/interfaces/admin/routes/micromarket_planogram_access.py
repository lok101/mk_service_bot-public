from __future__ import annotations

import logging
import time
from uuid import UUID

from beartype import beartype

from src.application.master_data import MachineKind, MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    MicromarketCatalogOption,
)
from src.application.reference_data import MsEntityKind
from src.domain.ids import MachineId
from src.interfaces.admin.deps import AdminHttpDeps

_LOGGER = logging.getLogger("src.interfaces.admin.routes.micromarket_planogram")


@beartype
def _require_micromarket_machine(
    stores: MasterDataStores,
    machine_id: str,
) -> MasterMachine | None:
    machine = stores.machines.get(MachineId(machine_id))
    if machine is None or machine.kind is not MachineKind.MICRO_MARKET:
        return None
    return machine


@beartype
def _sellable_catalog_codes(deps: AdminHttpDeps) -> set[str]:
    catalog = deps.provider.product_catalog_or_none()
    if catalog is None:
        return set()
    return {
        code for code, entry in catalog.by_code.items() if entry.entity_kind is MsEntityKind.PRODUCT
    }


_PATH_ALLOWED_CODES_CACHE: dict[tuple[UUID, ...], frozenset[str]] = {}

_PATH_ALLOWED_CODES_FAILED_AT: dict[tuple[UUID, ...], float] = {}

_PATH_ALLOWED_CODES_FAIL_COOLDOWN_SEC = 300.0


@beartype
async def _path_allowed_codes(deps: AdminHttpDeps) -> frozenset[str] | None:
    """None = no folder filter (all sellable). Empty frozenset = filter active, no matches."""
    folder_ids = tuple(deps.micromarket_ms_product_folder_ids)
    if not folder_ids:
        return None
    reader = deps.micromarket_assortment_reader
    if reader is None:
        return frozenset()
    cached = _PATH_ALLOWED_CODES_CACHE.get(folder_ids)
    if cached is not None:
        return cached
    failed_at = _PATH_ALLOWED_CODES_FAILED_AT.get(folder_ids)
    if failed_at is not None:
        if time.monotonic() - failed_at < _PATH_ALLOWED_CODES_FAIL_COOLDOWN_SEC:
            return None
        _PATH_ALLOWED_CODES_FAILED_AT.pop(folder_ids, None)
    try:
        entries = await reader.list_by_folder_ids(
            entity_kind="product",
            folder_ids=folder_ids,
        )
    except Exception as error:
        _PATH_ALLOWED_CODES_FAILED_AT[folder_ids] = time.monotonic()
        _LOGGER.warning(
            "micromarket_planogram_folder_filter_failed",
            extra={
                "folder_ids": [str(folder_id) for folder_id in folder_ids],
                "error": str(error),
            },
        )
        return None
    result = frozenset(entry.code for entry in entries if entry.code)
    _PATH_ALLOWED_CODES_CACHE[folder_ids] = result
    return result


@beartype
def _catalog_options(
    deps: AdminHttpDeps,
    *,
    path_allowed_codes: frozenset[str] | None,
) -> tuple[MicromarketCatalogOption, ...]:
    catalog = deps.provider.product_catalog_or_none()
    if catalog is None:
        return ()
    products = tuple(
        MicromarketCatalogOption(
            product_code=entry.code,
            name=entry.name,
        )
        for entry in catalog.by_code.values()
        if entry.entity_kind is MsEntityKind.PRODUCT
    )
    if path_allowed_codes is None:
        return products
    return tuple(product for product in products if product.product_code in path_allowed_codes)


@beartype
def _machine_multiplier_display(deps: AdminHttpDeps, machine: MasterMachine) -> str:
    store = deps.micromarket_machine_multiplier_store
    if store is None:
        return "1"
    value = store.get(machine.machine_id.value)
    return "1" if value is None else str(value)
