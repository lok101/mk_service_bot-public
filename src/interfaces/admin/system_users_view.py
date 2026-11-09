from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

from src.application.master_data import SystemUserRecord, SystemUserStore
from src.application.shared import resolve_admin_nav_tree
from src.domain.system_user import (
    NAV_ALIAS_PANELS,
    PLANOGRAM_OPERATOR_NAV_PANELS,
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
)
from src.interfaces.admin.deps import AdminHttpDeps

_PANEL_NAV: tuple[tuple[AdminPanel, str, str, str], ...] = (
    (AdminPanel.ROSTER, "/admin/roster", "Roster", "admin-icon-roster"),
    (AdminPanel.MASTER_DATA, "/admin/machines", "Парк", "admin-icon-master-data"),
    (AdminPanel.VISIT_BOARD, "/admin/visit-board", "Визиты", "admin-icon-visit-board"),
    (
        AdminPanel.VISIT_BOARD,
        "/admin/machine-incidents",
        "Инциденты",
        "admin-icon-visit-board",
    ),
    (
        AdminPanel.VISIT_BOARD,
        "/admin/machine-incidents/history",
        "История инцидентов",
        "admin-icon-visit-board",
    ),
    (
        AdminPanel.VISIT_PHOTO_REVIEW,
        "/admin/visit-photo-review",
        "Разбор фото",
        "admin-icon-visit-photo-review",
    ),
    (
        AdminPanel.SETTLEMENT_ANALYSIS,
        "/admin/settlement-analysis",
        "Сверка",
        "admin-icon-settlement-analysis",
    ),
    (
        AdminPanel.MATRIX_PRICING,
        "/admin/matrix-pricing",
        "Правила цены",
        "admin-icon-matrix-pricing",
    ),
    (
        AdminPanel.MATRIX_SKU_CATALOG,
        "/admin/matrix-sku-catalog",
        "SKU матрицы",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.TECHNICIANS,
        "/admin/technicians",
        "Техники",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.COMPANIES,
        "/admin/companies",
        "Компании",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.DOMAIN_PRODUCTS,
        "/admin/domain-products",
        "Товары",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.DOMAIN_PRODUCTS,
        "/admin/coffee-border-registration",
        "Регистрация границы МС→техник",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.COFFEE_RECIPES,
        "/admin/coffee-drinks",
        "Напитки и состав",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.COFFEE_RECIPES,
        "/admin/coffee-ingredients",
        "Кофейные ингредиенты",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.MICROMARKET_PLANOGRAMS,
        "/admin/micromarket-planograms",
        "Холодильники",
        "admin-icon-master-data",
    ),
    (
        AdminPanel.MICROMARKET_PLANOGRAMS,
        "/admin/snack-planograms",
        "Снеки",
        "admin-icon-master-data",
    ),
    (AdminPanel.USERS, "/admin/users", "Доступ", "admin-icon-users"),
    (
        AdminPanel.NAV_SETTINGS,
        "/admin/nav-settings",
        "Настройки меню",
        "admin-icon-nav-settings",
    ),
)

_PANEL_NAV_BY_PANEL: dict[AdminPanel, tuple[str, str, str]] = {}
for _panel, _href, _label, _icon_class in _PANEL_NAV:
    if _panel not in _PANEL_NAV_BY_PANEL:
        _PANEL_NAV_BY_PANEL[_panel] = (_href, _label, _icon_class)


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavItem:
    href: str
    label: str
    panel: AdminPanel


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavPanelView:
    kind: Literal["panel"]
    href: str
    label: str
    panel: AdminPanel
    icon_class: str
    active: bool


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavFolderView:
    kind: Literal["folder"]
    folder_id: str
    title: str
    children: tuple[AdminNavPanelView, ...]
    active: bool


@beartype
@dataclass(frozen=True, slots=True)
class SystemUserRowView:
    user_id: str
    name: str
    telegram_user_id: int
    bot_role: str
    technician_id: str
    is_active: bool
    company_roles: frozenset[CompanyRole]


@beartype
@dataclass(frozen=True, slots=True)
class SystemUsersPageView:
    rows: tuple[SystemUserRowView, ...]
    bot_roles: tuple[tuple[str, str], ...]
    all_company_roles: tuple[CompanyRole, ...]
    company_role_labels: dict[str, str]


@beartype
def panel_path_is_active(request_path: str, href: str) -> bool:
    return request_path == href or request_path.startswith(f"{href}/")


@beartype
def build_nav_items(
    deps: AdminHttpDeps,
    *,
    telegram_user_id: int | None,
) -> tuple[AdminNavItem, ...]:
    allowed = _allowed_panels(deps, telegram_user_id=telegram_user_id)
    items: list[AdminNavItem] = []
    for panel, href, label, _icon_class in _PANEL_NAV:
        if not _panel_mounted(deps, panel):
            continue
        if not _nav_href_mounted(deps, href):
            continue
        if panel in NAV_ALIAS_PANELS:
            if AdminPanel.MASTER_DATA not in allowed:
                continue
        elif panel in PLANOGRAM_OPERATOR_NAV_PANELS:
            if AdminPanel.MICROMARKET_PLANOGRAMS not in allowed:
                continue
        elif panel not in allowed:
            continue
        items.append(AdminNavItem(href=href, label=label, panel=panel))
    return tuple(items)


@beartype
def build_nav_tree_for_request(
    deps: AdminHttpDeps,
    *,
    telegram_user_id: int | None,
    request_path: str,
) -> tuple[AdminNavPanelView | AdminNavFolderView, ...]:
    store = deps.admin_nav_structure_store
    raw = None if store is None else store.get()
    allowed = _allowed_panels(deps, telegram_user_id=telegram_user_id)
    mounted = _mounted_panels(deps)
    resolved = resolve_admin_nav_tree(raw, allowed=allowed, mounted=mounted)
    views: list[AdminNavPanelView | AdminNavFolderView] = []
    for node in resolved:
        if node.kind == "panel":
            views.extend(_panel_views(node.panel, request_path=request_path, deps=deps))
            continue
        children = tuple(
            view
            for child in node.children
            for view in _panel_views(child, request_path=request_path, deps=deps)
        )
        views.append(
            AdminNavFolderView(
                kind="folder",
                folder_id=node.folder_id,
                title=node.title,
                children=children,
                active=any(child.active for child in children),
            )
        )
    return tuple(views)


@beartype
def _nav_href_mounted(deps: AdminHttpDeps, href: str) -> bool:
    if href == "/admin/micromarket-planograms":
        return _fridge_screen_mounted(deps)
    if href == "/admin/snack-planograms":
        return _snack_screen_mounted(deps)
    if href == "/admin/coffee-drinks":
        return deps.domain_product_store is not None and deps.coffee_recipe_repo is not None
    if href == "/admin/coffee-ingredients":
        return deps.domain_product_store is not None and deps.catalog_product_lookup is not None
    if href == "/admin/coffee-border-registration":
        return deps.domain_product_store is not None and deps.border_registration_store is not None
    return True


@beartype
def _panel_views(
    panel: AdminPanel,
    *,
    request_path: str,
    deps: AdminHttpDeps,
) -> tuple[AdminNavPanelView, ...]:
    rows = [
        (href, label, icon_class)
        for nav_panel, href, label, icon_class in _PANEL_NAV
        if nav_panel is panel and _nav_href_mounted(deps, href)
    ]
    if not rows:
        href, label, icon_class = _PANEL_NAV_BY_PANEL[panel]
        if not _nav_href_mounted(deps, href):
            return ()
        rows = [(href, label, icon_class)]
    return tuple(
        AdminNavPanelView(
            kind="panel",
            href=href,
            label=label,
            panel=panel,
            icon_class=icon_class,
            active=panel_path_is_active(request_path, href),
        )
        for href, label, icon_class in rows
    )


@beartype
def _panel_view(
    panel: AdminPanel,
    *,
    request_path: str,
    deps: AdminHttpDeps,
) -> AdminNavPanelView:
    return _panel_views(panel, request_path=request_path, deps=deps)[0]


@beartype
def build_system_users_page_view(
    store: SystemUserStore,
) -> SystemUsersPageView:
    records = sorted(store.list_all(), key=_sort_key)
    rows = tuple(_row_from_record(record) for record in records)
    bot_roles = tuple((role.value, role.label_ru) for role in BotRole)
    all_company_roles = tuple(CompanyRole)
    company_role_labels = {role.value: role.label_ru for role in CompanyRole}
    return SystemUsersPageView(
        rows=rows,
        bot_roles=bot_roles,
        all_company_roles=all_company_roles,
        company_role_labels=company_role_labels,
    )


@beartype
def _allowed_panels(
    deps: AdminHttpDeps,
    *,
    telegram_user_id: int | None,
) -> frozenset[AdminPanel]:
    if telegram_user_id is None:
        return frozenset()
    if not deps.users_enabled:
        mounted = set(_mounted_panels(deps))
        if mounted & NAV_ALIAS_PANELS:
            mounted.add(AdminPanel.MASTER_DATA)
        if (
            _fridge_screen_mounted(deps)
            or _snack_screen_mounted(deps)
            or deps.domain_product_store is not None
        ):
            mounted.add(AdminPanel.MICROMARKET_PLANOGRAMS)
        return frozenset(mounted)
    snapshot = deps.provider.system_users_or_none()
    if snapshot is None:
        return frozenset()
    user = snapshot.users_by_telegram_id.get(telegram_user_id)
    if user is None or not user.is_active:
        return frozenset()
    return user.panels


@beartype
def _mounted_panels(deps: AdminHttpDeps) -> frozenset[AdminPanel]:
    panels: set[AdminPanel] = {AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS}
    if deps.master_stores is not None or deps.technicians_enabled:
        panels.add(AdminPanel.MASTER_DATA)
        if deps.build_visit_board is not None:
            panels.add(AdminPanel.VISIT_BOARD)
    if deps.visit_photo_review_enabled and deps.review_queries is not None:
        panels.add(AdminPanel.VISIT_PHOTO_REVIEW)
    if deps.system_user_store is not None and deps.save_system_users is not None:
        panels.add(AdminPanel.USERS)
    if (
        deps.settlement_analysis_enabled
        and deps.build_settlement_analysis_tree is not None
        and deps.aggregate_settlement_clusters is not None
        and deps.build_session_analysis_view is not None
        and deps.build_period_analysis_view is not None
        and deps.settlement_analysis_prefs_store is not None
    ):
        panels.add(AdminPanel.SETTLEMENT_ANALYSIS)
    if deps.master_stores is not None and deps.matrix_base_margin_store is not None:
        panels.add(AdminPanel.MATRIX_PRICING)
    if deps.master_stores is not None and deps.sku_catalog_master_enabled:
        panels.add(AdminPanel.MATRIX_SKU_CATALOG)
    if deps.technicians_enabled and deps.save_field_staff is not None:
        panels.add(AdminPanel.TECHNICIANS)
    if deps.companies_enabled and deps.create_company is not None:
        panels.add(AdminPanel.COMPANIES)
    if deps.domain_product_store is not None:
        panels.add(AdminPanel.DOMAIN_PRODUCTS)
    if deps.domain_product_store is not None and deps.catalog_product_lookup is not None:
        panels.add(AdminPanel.COFFEE_RECIPES)
    if _fridge_screen_mounted(deps) or _snack_screen_mounted(deps):
        panels.add(AdminPanel.MICROMARKET_PLANOGRAMS)
    return frozenset(panels)


@beartype
def _fridge_screen_mounted(deps: AdminHttpDeps) -> bool:
    return (
        deps.master_stores is not None
        and deps.micromarket_planogram_store is not None
        and deps.micromarket_stock_store is not None
    )


@beartype
def _snack_screen_mounted(deps: AdminHttpDeps) -> bool:
    return (
        deps.layout_master_enabled
        and deps.snack_layout_store is not None
        and deps.master_stores is not None
    )


@beartype
def _panel_mounted(deps: AdminHttpDeps, panel: AdminPanel) -> bool:
    match panel:
        case AdminPanel.ROSTER:
            return True
        case AdminPanel.MASTER_DATA:
            return deps.master_stores is not None or (
                deps.technicians_enabled and deps.save_field_staff is not None
            )
        case AdminPanel.VISIT_BOARD:
            return deps.master_stores is not None and deps.build_visit_board is not None
        case AdminPanel.VISIT_PHOTO_REVIEW:
            return deps.visit_photo_review_enabled and deps.review_queries is not None
        case AdminPanel.USERS:
            return deps.system_user_store is not None and deps.save_system_users is not None
        case AdminPanel.SETTLEMENT_ANALYSIS:
            return (
                deps.settlement_analysis_enabled
                and deps.build_settlement_analysis_tree is not None
                and deps.aggregate_settlement_clusters is not None
                and deps.build_session_analysis_view is not None
                and deps.build_period_analysis_view is not None
                and deps.settlement_analysis_prefs_store is not None
            )
        case AdminPanel.MATRIX_PRICING:
            return deps.master_stores is not None and deps.matrix_base_margin_store is not None
        case AdminPanel.MATRIX_SKU_CATALOG:
            return deps.master_stores is not None and deps.sku_catalog_master_enabled
        case AdminPanel.TECHNICIANS:
            return deps.technicians_enabled and deps.save_field_staff is not None
        case AdminPanel.COMPANIES:
            return deps.companies_enabled and deps.create_company is not None
        case AdminPanel.DOMAIN_PRODUCTS:
            return deps.domain_product_store is not None
        case AdminPanel.COFFEE_RECIPES:
            return deps.domain_product_store is not None and deps.catalog_product_lookup is not None
        case AdminPanel.MICROMARKET_PLANOGRAMS:
            return _fridge_screen_mounted(deps) or _snack_screen_mounted(deps)
        case AdminPanel.NAV_SETTINGS:
            return True


mounted_admin_panels = _mounted_panels


@beartype
def _row_from_record(record: SystemUserRecord) -> SystemUserRowView:
    user: SystemUser = record.user
    technician_id = "" if user.technician_id is None else user.technician_id.value
    return SystemUserRowView(
        user_id=user.user_id.value,
        name=user.name,
        telegram_user_id=user.telegram_user_id,
        bot_role=user.role.value,
        technician_id=technician_id,
        is_active=user.is_active,
        company_roles=user.company_roles,
    )


@beartype
def _sort_key(record: SystemUserRecord) -> tuple[str, int]:
    return (record.user.user_id.value, record.user.telegram_user_id)
