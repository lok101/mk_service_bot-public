from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from beartype import beartype
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import MachineKind, MasterDataStores
from src.application.micromarket_loading import (
    CreateMicromarketSupplyOrder,
    DownloadMicromarketSupplyOrder,
    LiveNeedMachine,
    MicromarketSupplyOrderStore,
    SupplyOrderCreated,
    SupplyOrderEmptySelection,
    SupplyOrderInvalidArrival,
    SupplyOrderMissingShelfLife,
    SupplyOrderMsUnavailable,
    SupplyOrderNoPositiveNeed,
    SupplyOrderNotFound,
    SupplyOrderProductsNotLinked,
)
from src.domain.ids import MachineId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.micromarket_planograms_list import _live_need_machine

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@beartype
def _positive_need_labels(
    machines: tuple[LiveNeedMachine, ...],
) -> tuple[tuple[str, str], ...]:
    labels: dict[str, str] = {}
    for machine in machines:
        for line in machine.lines:
            if line.need_qty <= 0:
                continue
            if line.product_code not in labels:
                labels[line.product_code] = line.name or line.product_code
    return tuple(sorted(labels.items()))


@beartype
def _format_sku_list(items: tuple[tuple[str, str], ...]) -> list[str]:
    parts: list[str] = []
    for code, name in items:
        label = code.strip()
        display = (name or "").strip()
        if label and display and display != label:
            parts.append(f"{label} ({display})")
        elif label:
            parts.append(label)
        elif display:
            parts.append(display)
        else:
            parts.append("(без кода)")
    return parts


def _unlinked_flash(items: tuple[tuple[str, str], ...]) -> str:
    parts = _format_sku_list(items)
    if not parts:
        return "Сначала свяжите товары с карточками МойСклада"
    return "Сначала свяжите товары с карточками МойСклада:\n" + "\n".join(parts)


def _missing_shelf_life_flash(items: tuple[tuple[str, str], ...]) -> str:
    parts = _format_sku_list(items)
    if not parts:
        return "Укажите «Срок хранения» в МойСкладе для готовой еды"
    return "Укажите «Срок хранения» в МойСкладе для готовой еды:\n" + "\n".join(parts)


def _ms_unavailable_flash() -> str:
    return "Не удалось получить данные МойСклада для классификации заказа"


def _invalid_arrival_flash() -> str:
    return "Укажите дату и время прибытия в будущем"


def _forecast_unavailable_notice(items: tuple[tuple[str, str], ...]) -> str:
    parts = _format_sku_list(items)
    if not parts:
        return "Прогноз недоступен — заказ создан по стандартной потребности"
    return "Прогноз недоступен для SKU (заказ создан по стандартной потребности):\n" + "\n".join(
        parts,
    )


def _parse_expected_arrival(raw: str, *, timezone: object) -> datetime | None:
    if not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)  # type: ignore[arg-type]
    return parsed


@beartype
def _create_supply_order(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    selected_ids: list[str],
    arrival_raw: str,
) -> Response:
    supply_store = deps.micromarket_supply_order_store
    assert supply_store is not None
    if not selected_ids:
        return Response(status_code=400, content="empty_selection")
    expected_arrival = _parse_expected_arrival(arrival_raw, timezone=deps.timezone)
    live_machines: list[LiveNeedMachine] = []
    for raw_id in selected_ids:
        machine = stores.machines.get(MachineId(raw_id))
        if machine is None or machine.kind is not MachineKind.MICRO_MARKET:
            return Response(status_code=404)
        live_machines.append(_live_need_machine(deps, machine))
    products = deps.domain_product_store
    if products is None:
        unlinked = _positive_need_labels(tuple(live_machines))
        return Response(status_code=400, content=_unlinked_flash(unlinked))
    mirrors = (
        deps.procurement_mirror_store
        if deps.procurement_mirror_enabled and deps.procurement_mirror_store is not None
        else None
    )
    category_facts = deps.supply_order_category_facts
    if category_facts is None:
        return Response(status_code=400, content=_ms_unavailable_flash())
    forecast = deps.supply_order_demand_forecast
    if forecast is None:
        return Response(status_code=400, content=_ms_unavailable_flash())
    result = CreateMicromarketSupplyOrder(
        store=supply_store,
        clock=deps.now_factory,
        products=products,
        category_facts=category_facts,
        snacks_folder_id=deps.supply_order_snacks_folder_id,
        ready_meals_folder_id=deps.supply_order_ready_meals_folder_id,
        shelf_life_days_threshold=deps.supply_order_shelf_life_days_threshold,
        forecast=forecast,
        mirrors=mirrors,
    ).execute(machines=tuple(live_machines), expected_arrival_at=expected_arrival)
    if isinstance(result, SupplyOrderInvalidArrival):
        return Response(status_code=400, content=_invalid_arrival_flash())
    if isinstance(result, (SupplyOrderEmptySelection, SupplyOrderNoPositiveNeed)):
        return Response(status_code=400, content="empty_or_zero_need")
    if isinstance(result, SupplyOrderProductsNotLinked):
        return Response(status_code=400, content=_unlinked_flash(result.items))
    if isinstance(result, SupplyOrderMissingShelfLife):
        return Response(status_code=400, content=_missing_shelf_life_flash(result.items))
    if isinstance(result, SupplyOrderMsUnavailable):
        return Response(status_code=400, content=_ms_unavailable_flash())
    assert isinstance(result, SupplyOrderCreated)
    order_id = result.order.order_id
    url = f"/admin/micromarket-planograms?tab=orders&download={order_id}"
    if result.forecast_unavailable_items:
        url += "&notice=" + quote(_forecast_unavailable_notice(result.forecast_unavailable_items))
    return RedirectResponse(url=url, status_code=303)


@beartype
def _download_supply_order(
    store: MicromarketSupplyOrderStore,
    order_id: str,
) -> Response:
    result = DownloadMicromarketSupplyOrder(store=store).execute(order_id)
    if isinstance(result, SupplyOrderNotFound):
        return Response(status_code=404)
    return Response(
        content=result,
        media_type=_XLSX_MEDIA,
        headers={
            "Content-Disposition": (
                f'attachment; filename="micromarket-supply-order-{order_id}.xlsx"'
            ),
        },
    )
