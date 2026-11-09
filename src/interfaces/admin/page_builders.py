"""Sync admin page builders for asyncio.to_thread offload.

Live MoySklad snack assortment is preloaded in the async handler and passed as
``ms_names_by_code``; inside the worker thread only sync Mongo, catalog, and
purchase readers run.

Visit-board, settlement-analysis, and roster GET pages offload their sync UC /
view-model work here; HTML render stays in async handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from beartype import beartype

from src.application.inventory_reconciliation import resolve_current_company_name
from src.application.master_data import (
    MasterDataStores,
    MasterMachine,
    MasterMachineStore,
    TechnicianStore,
)
from src.application.matrix_automation import SnackMachineLayout, kit_product_code
from src.application.reference_data import BootstrapLocationRosterDraft
from src.application.shared import parse_sheet_decimal
from src.application.sheets import list_all_machines_from_snapshot
from src.application.technician_settlement import (
    SettlementAnalysisPrefs,
    UnknownAnalysisSession,
)
from src.domain.calendar import operational_day
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.machine_layout_view import (
    LayoutProductOption,
    SnackPlanogramProfileView,
    build_layout_product_options,
    build_snack_layout_profile_view,
    layout_product_options_json,
    layout_section_visible,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.roster_view import RosterViewModel, build_roster_view_model

_LOGGER = logging.getLogger(__name__)

_SETTLEMENT_MODE_LABELS: dict[str, str] = {
    "inventory_delta": "инвентаризация склада",
    "exit_warehouse_closed": "exit",
}


@dataclass(frozen=True, slots=True)
class VisitBoardPagePayload:
    redirect: str | None
    board: object | None


@dataclass(frozen=True, slots=True)
class SettlementAnalysisPagePayload:
    status_code: int
    template_kwargs: dict[str, object]


@dataclass(frozen=True, slots=True)
class RosterPagePayload:
    view: RosterViewModel


@dataclass(frozen=True, slots=True)
class MachineProfilePageData:
    machine: MasterMachine
    display_name: str
    company_name: str


@dataclass(frozen=True, slots=True)
class MachinePlanogramPageData:
    machine: MasterMachine
    display_name: str
    company_name: str
    layout_section: SnackPlanogramProfileView
    layout_archived_warning: str | None = None
    layout_autocomplete_product_options: tuple[LayoutProductOption, ...] = ()
    layout_autocomplete_options_json: str = "{}"


def _layout_product_multipliers(deps: AdminHttpDeps) -> dict[str, Decimal]:
    store = deps.matrix_sku_catalog_store
    if store is None:
        return {}
    return {entry.product_code: entry.product_multiplier for entry in store.list_all()}


def _layout_purchases_for_codes(
    deps: AdminHttpDeps,
    codes: frozenset[str],
) -> dict[str, Decimal] | None:
    reader = deps.purchase_attributes_reader
    if reader is None or not codes:
        return {}
    try:
        result = reader.fetch_attributes(codes)
    except Exception:
        _LOGGER.exception("admin_layout_purchase_ms_fail")
        return None
    purchases: dict[str, Decimal] = {}
    for code, (purchase_raw, _capacity) in result.attributes.items():
        try:
            purchase = parse_sheet_decimal(str(purchase_raw))
        except ValueError, InvalidOperation:
            continue
        if purchase > 0:
            purchases[code] = purchase
    return purchases


def _layout_stock_by_line(
    deps: AdminHttpDeps,
    *,
    machine_code: str,
    logical_matrix_name: str,
    line_numbers: frozenset[int],
) -> dict[int, Decimal]:
    store = deps.snack_stock_store
    if store is None or not line_numbers:
        return {}
    stock = store.load(machine_code)
    if stock is None:
        return {}
    return {line: stock.qty(machine_code, logical_matrix_name, line) for line in line_numbers}


def _layout_snapshot_deploy_by_line(
    deps: AdminHttpDeps,
    *,
    machine_code: str,
    logical_matrix_name: str,
    line_numbers: frozenset[int],
) -> dict[int, Decimal]:
    snapshots = deps.matrix_price_snapshot_store
    if snapshots is None or not line_numbers:
        return {}
    out: dict[int, Decimal] = {}
    for line in line_numbers:
        doc = snapshots.get_latest_line(
            machine_code=machine_code,
            logical_matrix_name=logical_matrix_name,
            line_number=line,
        )
        if doc is None:
            continue
        for record in doc.lines:
            if record.line_number == line and record.outcome == "applied":
                out[line] = Decimal(record.deploy_price)
                break
    return out


def _auto_sync_allowed_for_layout(
    deps: AdminHttpDeps,
    *,
    machine_code: str,
) -> bool:
    snapshots = deps.matrix_price_snapshot_store
    layout_store = deps.snack_layout_store
    if snapshots is None or layout_store is None:
        return False
    layout = layout_store.get(machine_code)
    logical_matrix_name = layout.logical_matrix_name if layout is not None else machine_code
    return snapshots.has_unit_snapshot(
        machine_code=machine_code,
        logical_matrix_name=logical_matrix_name,
    )


def _build_layout_product_options_sync(
    deps: AdminHttpDeps,
    *,
    ms_names_by_code: dict[str, tuple[str, bool]] | None,
) -> tuple[LayoutProductOption, ...]:
    ms_names: dict[str, str] = {}
    catalog_by_code: dict[str, tuple[str, int]] = {}
    if deps.sku_catalog_master_enabled:
        if ms_names_by_code is not None:
            # Include archived: hydrates legacy cell display names on GET.
            ms_names = {code: name for code, (name, _archived) in ms_names_by_code.items()}
            known = frozenset(ms_names)
        else:
            known = frozenset()
        store = deps.matrix_sku_catalog_store
        if store is not None:
            for entry in store.list_all():
                catalog_by_code[entry.product_code] = (entry.display_name, entry.capacity)
    else:
        catalog = deps.provider.product_catalog_or_none()
        known = frozenset(catalog.by_code.keys()) if catalog is not None else frozenset()
        if catalog is not None:
            ms_names = {code: entry.name for code, entry in catalog.by_code.items()}
    return build_layout_product_options(
        known_codes=known,
        ms_names=ms_names,
        catalog_by_code=catalog_by_code,
    )


def _layout_autocomplete_product_options(
    product_options: tuple[LayoutProductOption, ...],
    *,
    ms_names_by_code: dict[str, tuple[str, bool]] | None,
    archived_product_codes: frozenset[str] | None = None,
) -> tuple[LayoutProductOption, ...]:
    if archived_product_codes is not None:
        archived = archived_product_codes
    elif ms_names_by_code is not None:
        archived = frozenset(
            code for code, (_name, is_archived) in ms_names_by_code.items() if is_archived
        )
    else:
        return product_options
    if not archived:
        return product_options
    return tuple(opt for opt in product_options if opt.product_code not in archived)


def build_snack_layout_section(
    deps: AdminHttpDeps,
    *,
    machine: MasterMachine,
    machines: MasterMachineStore,
    product_options: tuple[LayoutProductOption, ...],
) -> SnackPlanogramProfileView | None:
    layout_store = deps.snack_layout_store
    assert layout_store is not None
    machine_code = machine.machine_id.value
    layout = layout_store.get(machine_code)
    products = deps.domain_product_store
    cells = layout.cells if layout is not None else ()
    codes = frozenset(code for cell in cells if (code := kit_product_code(cell, products)))
    line_numbers = frozenset(cell.line_number for cell in cells)
    logical_matrix_name = layout.logical_matrix_name if layout is not None else machine_code
    base_margin = None
    if deps.matrix_base_margin_store is not None:
        base_margin = deps.matrix_base_margin_store.get()
    return build_snack_layout_profile_view(
        machine=machine,
        layout_store=layout_store,
        machines=machines,
        product_options=product_options,
        base_margin=base_margin,
        purchases=_layout_purchases_for_codes(deps, codes),
        product_multipliers=_layout_product_multipliers(deps),
        auto_sync_allowed=_auto_sync_allowed_for_layout(
            deps,
            machine_code=machine_code,
        ),
        stock_by_line=_layout_stock_by_line(
            deps,
            machine_code=machine_code,
            logical_matrix_name=logical_matrix_name,
            line_numbers=line_numbers,
        ),
        snapshot_deploy_by_line=_layout_snapshot_deploy_by_line(
            deps,
            machine_code=machine_code,
            logical_matrix_name=logical_matrix_name,
            line_numbers=line_numbers,
        ),
        products=products,
    )


@beartype
def build_machine_profile_page_sync(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine_id: str,
    *,
    ms_names_by_code: dict[str, tuple[str, bool]] | None,
) -> MachineProfilePageData | None:
    machine = stores.machines.get(MachineId(machine_id))
    if machine is None:
        return None
    display_name = machine_profile_display_name(stores, machine)
    company_name = ""
    occupancy_store = deps.company_occupancy_store
    if occupancy_store is not None:
        company_name = resolve_current_company_name(
            occupancy_store.list_for_machine(machine.machine_id),
            deps.company_display_names or {},
        )
    return MachineProfilePageData(
        machine=machine,
        display_name=display_name,
        company_name=company_name,
    )


def _layout_archived_warning_message(
    *,
    layout: SnackMachineLayout | None,
    ms_names_by_code: dict[str, tuple[str, bool]] | None,
) -> str | None:
    if ms_names_by_code is None or layout is None:
        return None
    layout_codes = {code for cell in layout.cells if (code := cell.product_code) is not None}
    archived_in_layout = sorted(
        code for code in layout_codes if ms_names_by_code.get(code, ("", False))[1]
    )
    if not archived_in_layout:
        return None
    codes = ", ".join(archived_in_layout)
    return (
        f"В раскладке есть архивные SKU МойСклад: {codes}. "
        "Сохранение существующих ячеек допускается; новые архивные коды добавить нельзя."
    )


@beartype
def build_machine_planogram_page_sync(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine_id: str,
    *,
    ms_names_by_code: dict[str, tuple[str, bool]] | None,
) -> MachinePlanogramPageData | None:
    machine = stores.machines.get(MachineId(machine_id))
    if machine is None:
        return None
    if not layout_section_visible(
        layout_master_enabled=deps.layout_master_enabled,
        machine=machine,
    ):
        return None
    layout_store = deps.snack_layout_store
    if layout_store is None:
        return None
    display_name = machine_profile_display_name(stores, machine)
    company_name = ""
    occupancy_store = deps.company_occupancy_store
    if occupancy_store is not None:
        company_name = resolve_current_company_name(
            occupancy_store.list_for_machine(machine.machine_id),
            deps.company_display_names or {},
        )
    product_options = _build_layout_product_options_sync(
        deps,
        ms_names_by_code=ms_names_by_code,
    )
    autocomplete_options = _layout_autocomplete_product_options(
        product_options,
        ms_names_by_code=ms_names_by_code,
    )
    layout_section = build_snack_layout_section(
        deps,
        machine=machine,
        machines=stores.machines,
        product_options=product_options,
    )
    if layout_section is None:
        return None
    return MachinePlanogramPageData(
        machine=machine,
        display_name=display_name,
        company_name=company_name,
        layout_section=layout_section,
        layout_archived_warning=_layout_archived_warning_message(
            layout=layout_store.get(machine.machine_id.value),
            ms_names_by_code=ms_names_by_code,
        ),
        layout_autocomplete_product_options=autocomplete_options,
        layout_autocomplete_options_json=layout_product_options_json(autocomplete_options),
    )


def _technician_options(deps: AdminHttpDeps) -> tuple[tuple[str, str], ...]:
    directory = deps.provider.technicians_directory()
    return tuple(
        (technician_id.value, name)
        for technician_id, name in sorted(
            directory.names_by_id.items(),
            key=lambda item: item[0].value,
        )
    )


def _parse_sessions_csv(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _prefs_sku_rows(
    prefs: SettlementAnalysisPrefs,
    aggregate: object | None,
) -> tuple[tuple[str, str], ...]:
    names: dict[str, str] = {}
    codes: set[str] = set(prefs.unit_prices) | set(prefs.recoverable_product_codes)
    rows = getattr(aggregate, "rows", None)
    if rows is not None:
        for row in rows:
            codes.add(row.product_code)
            product_name = getattr(row, "product_name", "")
            if product_name:
                names[row.product_code] = product_name
    return tuple((code, names.get(code, code)) for code in sorted(codes))


def _active_store_technician_ids(deps: AdminHttpDeps) -> frozenset[TechnicianId] | None:
    if not deps.technicians_enabled or deps.technician_store is None:
        return None
    store: TechnicianStore = deps.technician_store
    return frozenset(
        technician.technician_id for technician in store.list_all() if technician.is_active
    )


@beartype
def build_visit_board_page_sync(
    deps: AdminHttpDeps,
    *,
    year_raw: str | None,
    month_raw: str | None,
    now: datetime,
    visit_board_path: str,
) -> VisitBoardPagePayload:
    build_visit_board = deps.build_visit_board
    assert build_visit_board is not None
    today_ops = operational_day(now, deps.timezone, deps.day_end_hour)
    year, month = today_ops.year, today_ops.month
    if year_raw is not None or month_raw is not None:
        try:
            year = int(year_raw) if year_raw is not None else year
            month = int(month_raw) if month_raw is not None else month
            if month < 1 or month > 12:
                raise ValueError
        except TypeError, ValueError:
            return VisitBoardPagePayload(
                redirect=f"{visit_board_path}?year={today_ops.year}&month={today_ops.month}",
                board=None,
            )
    view = build_visit_board.execute(year=year, month=month, now=now)
    return VisitBoardPagePayload(redirect=None, board=view)


@beartype
def build_settlement_analysis_page_sync(
    deps: AdminHttpDeps,
    *,
    actor_telegram_user_id: int,
    technician_raw: str,
    sessions_raw: str,
) -> SettlementAnalysisPagePayload:
    tree_uc = deps.build_settlement_analysis_tree
    aggregate_uc = deps.aggregate_settlement_clusters
    prefs_store = deps.settlement_analysis_prefs_store
    assert tree_uc is not None and aggregate_uc is not None and prefs_store is not None

    technician_options = _technician_options(deps)
    selected_sessions = _parse_sessions_csv(sessions_raw)

    tree = None
    aggregate = None
    empty_message: str | None = None
    if not technician_raw:
        empty_message = "Выберите техника."
    else:
        try:
            technician_id = TechnicianId(technician_raw)
        except ValueError:
            empty_message = "Неизвестный техник."
            technician_raw = ""
        else:
            tree = tree_uc.execute(technician_id)
            if not tree.clusters:
                empty_message = "Нет завершённых сверки для выбранного техника."
            if selected_sessions:
                prefs = prefs_store.get(actor_telegram_user_id)
                try:
                    aggregate = aggregate_uc.execute(
                        technician_id=technician_id,
                        session_ids=selected_sessions,
                        prefs=prefs,
                    )
                except UnknownAnalysisSession:
                    return SettlementAnalysisPagePayload(status_code=400, template_kwargs={})

    prefs = prefs_store.get(actor_telegram_user_id)
    prefs_sku_rows = _prefs_sku_rows(prefs, aggregate)
    return SettlementAnalysisPagePayload(
        status_code=200,
        template_kwargs={
            "technician_options": technician_options,
            "selected_technician_id": technician_raw,
            "selected_sessions": selected_sessions,
            "sessions_csv": sessions_raw,
            "tree": tree,
            "aggregate": aggregate,
            "prefs": prefs,
            "prefs_sku_rows": prefs_sku_rows,
            "empty_message": empty_message,
            "mode_labels": _SETTLEMENT_MODE_LABELS,
        },
    )


@beartype
def build_roster_page_sync(
    deps: AdminHttpDeps,
    *,
    actor_telegram_user_id: int,
) -> RosterPagePayload:
    catalog = deps.provider.locations_catalog()
    catalog_ids = frozenset(machine.id for machine in list_all_machines_from_snapshot(catalog))
    BootstrapLocationRosterDraft(
        applied=deps.roster_store,
        draft=deps.roster_draft_store,
    ).execute(
        catalog_machine_ids=catalog_ids,
        now=deps.now_factory(),
        actor_telegram_user_id=actor_telegram_user_id,
    )
    view = build_roster_view_model(
        deps.provider,
        draft_store=deps.roster_draft_store,
        applied_store=deps.roster_store,
        active_technician_ids=_active_store_technician_ids(deps),
    )
    return RosterPagePayload(view=view)
