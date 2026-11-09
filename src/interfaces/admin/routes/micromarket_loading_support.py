from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs

from beartype import beartype

from src.application.master_data import MachineKind, MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    AssemblyOrderRejected,
    MicromarketLoadingCycleStore,
    resolve_ms_catalog_code,
)
from src.application.reference_data import MsEntityKind
from src.application.shared import parse_sheet_decimal
from src.domain.ids import MachineId
from src.domain.micromarket_loading.assembly_order import (
    DuplicateCatalogCode,
    InvalidAssemblyOrderTransition,
    MicromarketAssemblyOrder,
)
from src.domain.micromarket_loading.order import DraftLine, OrderStatus
from src.domain.micromarket_loading.quantities import need_qty
from src.domain.system_user import CompanyRole, has_access_administrator
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.user_facing_errors import AdminUserFacingError

_LOGGER = logging.getLogger(__name__)

_UNGROUPED_SHELF_LABEL = "Без полки"
_LAUNCH_STEPPER_MAX = 9999
_DRAFT_LAUNCH_STATUSES = frozenset(
    {None, OrderStatus.OPEN, OrderStatus.RECOUNTED},
)


@beartype
def _qty_display(qty: Decimal | None) -> str:
    if qty is None:
        return "—"
    if qty == qty.to_integral_value():
        return str(int(qty))
    return format(qty, "f").rstrip("0").rstrip(".")


class _DisabledMoveGateway:
    def warehouse_qty(self, product_code: str) -> Decimal:
        return Decimal("0")

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return {code: Decimal("0") for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        raise RuntimeError("micromarket loading move gateway is not configured")

    def delete_move(self, *, move_id: str) -> None:
        return None

    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        del order_id, now
        return False


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
def _cycle_is_open(cycle_store: MicromarketLoadingCycleStore, machine_code: str) -> bool:
    cycle = cycle_store.load(machine_code)
    return cycle is not None and cycle.status is OrderStatus.OPEN


@beartype
def _catalog_names(deps: AdminHttpDeps) -> dict[str, str]:
    catalog = deps.provider.product_catalog_or_none()
    if catalog is None:
        return {}
    return {
        code: entry.name
        for code, entry in catalog.by_code.items()
        if entry.entity_kind is MsEntityKind.PRODUCT
    }


@beartype
def _company_roles_may_ops_accept(roles: frozenset[CompanyRole] | set[CompanyRole]) -> bool:
    return has_access_administrator(roles) or CompanyRole.SERVICE_OPERATIONS_COORDINATOR in roles


@beartype
def _actor_may_ops_accept(deps: AdminHttpDeps, telegram_user_id: int) -> bool:
    snapshot = deps.provider.system_users_or_none()
    if snapshot is None:
        return False
    user = snapshot.users_by_telegram_id.get(telegram_user_id)
    if user is None or not user.is_active:
        return False
    return _company_roles_may_ops_accept(user.company_roles)


@beartype
def _fridge_workspace_url(
    machine_code: str,
    tab: str,
    *,
    order_id: str | None = None,
) -> str:
    if tab == "planogram":
        url = f"/admin/micromarket-planograms/{machine_code}"
    else:
        url = f"/admin/micromarket-planograms/{machine_code}?tab={tab}"
    if order_id:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}order={order_id}"
    return url


@beartype
def _loading_cycle_order_open(deps: AdminHttpDeps, machine_code: str) -> bool:
    cycle_store = deps.micromarket_loading_cycle_store
    if cycle_store is None:
        return False
    cycle = cycle_store.load(machine_code)
    return cycle is not None and cycle.status is OrderStatus.OPEN


@beartype
def _draft_lines_from_form(body: str) -> tuple[DraftLine, ...]:
    parsed = parse_qs(body, keep_blank_values=True)
    codes = parsed.get("product_code", [])
    lines: list[DraftLine] = []
    for index, code in enumerate(codes):
        product_code = code.strip()
        if not product_code:
            continue
        target = _int_at(parsed.get("target_qty", []), index, default=0)
        stock = _decimal_at(parsed.get("stock_qty", []), index, default=Decimal("0"))
        # need_qty from form is ignored for SoT; service field = live gap.
        live_need = need_qty(target_qty=target, shelf_qty=stock)
        launch = _decimal_at(parsed.get("launch_qty", []), index, default=Decimal("0"))
        lines.append(
            DraftLine(
                product_code=product_code,
                target_qty=target,
                stock_qty=stock,
                need_qty=live_need,
                launch_qty=launch,
            ),
        )
    return tuple(lines)


def _int_at(values: list[str], index: int, *, default: int) -> int:
    if index >= len(values):
        return default
    raw = values[index].strip()
    if not raw:
        return default
    return int(raw)


def _decimal_at(values: list[str], index: int, *, default: Decimal) -> Decimal:
    if index >= len(values):
        return default
    raw = values[index].strip()
    if not raw:
        return default
    try:
        return parse_sheet_decimal(raw)
    except ValueError:
        return default


@beartype
def _assembly_lines_from_form(body: str, deps: AdminHttpDeps) -> dict[str, Decimal]:
    parsed = parse_qs(body, keep_blank_values=True)
    codes = parsed.get("product_code", [])
    qtys = parsed.get("assembly_qty", [])
    lines: dict[str, Decimal] = {}
    for index, code in enumerate(codes):
        product_code = code.strip()
        if not product_code:
            continue
        qty = _decimal_at(qtys, index, default=Decimal("0"))
        if qty <= 0:
            continue
        catalog_code = resolve_ms_catalog_code(deps.domain_product_store, product_code)
        if catalog_code is None:
            catalog_code = product_code
        lines[catalog_code] = lines.get(catalog_code, Decimal("0")) + qty
    return lines


@beartype
def _assembly_order_lines_from_form(body: str) -> dict[str, Decimal]:
    parsed = parse_qs(body, keep_blank_values=True)
    codes = parsed.get("catalog_code", [])
    qtys = parsed.get("order_line_qty", [])
    lines: dict[str, Decimal] = {}
    for index, code in enumerate(codes):
        catalog_code = code.strip()
        if not catalog_code:
            continue
        qty = _decimal_at(qtys, index, default=Decimal("0"))
        if qty <= 0:
            continue
        lines[catalog_code] = qty
    return lines


@beartype
def _assembly_manage_error(result: object) -> AdminUserFacingError | None:
    from src.interfaces.admin.user_facing_errors import admin_error_present

    if isinstance(result, MicromarketAssemblyOrder):
        return None
    if isinstance(result, AssemblyOrderRejected):
        return admin_error_present(result.reason, targets=result.targets)
    if isinstance(result, DuplicateCatalogCode):
        return admin_error_present(
            f"duplicate_catalog_code:{result.catalog_code}",
            targets=(result.catalog_code,),
        )
    if isinstance(result, InvalidAssemblyOrderTransition):
        return admin_error_present(result.reason)
    return admin_error_present("assembly_order_rejected")


@beartype
def _assembly_manage_message(result: object) -> str | None:
    """Legacy string path; prefer `_assembly_manage_error` for UI."""
    error = _assembly_manage_error(result)
    return None if error is None else error.code
