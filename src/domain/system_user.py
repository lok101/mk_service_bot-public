from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from beartype import beartype

from src.domain.ids import TechnicianId


class BotRole(StrEnum):
    ADMINISTRATOR = "administrator"
    TECHNICIAN = "technician"
    NONE = "none"

    @property
    def label_ru(self) -> str:
        match self:
            case BotRole.ADMINISTRATOR:
                return "Администратор"
            case BotRole.TECHNICIAN:
                return "Техник"
            case BotRole.NONE:
                return "Нет доступа к боту"


class AdminPanel(StrEnum):
    ROSTER = "roster"
    MASTER_DATA = "master_data"
    USERS = "users"
    VISIT_BOARD = "visit_board"
    VISIT_PHOTO_REVIEW = "visit_photo_review"
    SETTLEMENT_ANALYSIS = "settlement_analysis"
    MATRIX_PRICING = "matrix_pricing"
    MATRIX_SKU_CATALOG = "matrix_sku_catalog"
    TECHNICIANS = "technicians"
    COMPANIES = "companies"
    DOMAIN_PRODUCTS = "domain_products"
    MICROMARKET_PLANOGRAMS = "micromarket_planograms"
    COFFEE_RECIPES = "coffee_recipes"
    NAV_SETTINGS = "nav_settings"


# Reserved for nav-only leaves gated by another permission checkbox.
# TECHNICIANS / COMPANIES / MATRIX_SKU_CATALOG are own checkboxes (LOK-281).
NAV_ALIAS_PANELS: frozenset[AdminPanel] = frozenset()

# Reserved for nav-only leaves gated by micromarket_planograms.
# DOMAIN_PRODUCTS is its own checkbox (LOK-240).
PLANOGRAM_OPERATOR_NAV_PANELS: frozenset[AdminPanel] = frozenset()


@beartype
def permission_panels() -> tuple[AdminPanel, ...]:
    hidden = NAV_ALIAS_PANELS | PLANOGRAM_OPERATOR_NAV_PANELS
    return tuple(panel for panel in AdminPanel if panel not in hidden)


class CompanyRole(StrEnum):
    ACCESS_ADMINISTRATOR = "access_administrator"
    SERVICE_OPERATIONS_COORDINATOR = "service_operations_coordinator"
    PLANOGRAM_CURATOR = "planogram_curator"
    COFFEE_TECHNOLOGIST = "coffee_technologist"
    SETTLEMENT_OPERATOR = "settlement_operator"
    PRICING_POLICY_HOLDER = "pricing_policy_holder"
    FIELD_TECHNICIAN = "field_technician"

    @property
    def label_ru(self) -> str:
        match self:
            case CompanyRole.ACCESS_ADMINISTRATOR:
                return "Администратор доступа"
            case CompanyRole.SERVICE_OPERATIONS_COORDINATOR:
                return "Координатор сервисных операций"
            case CompanyRole.PLANOGRAM_CURATOR:
                return "Куратор планограмм и товарной идентичности"
            case CompanyRole.COFFEE_TECHNOLOGIST:
                return "Технолог"
            case CompanyRole.SETTLEMENT_OPERATOR:
                return "Оператор сверки"
            case CompanyRole.PRICING_POLICY_HOLDER:
                return "Держатель ценовой политики"
            case CompanyRole.FIELD_TECHNICIAN:
                return "Полевой техник"


_ROLE_PANELS: dict[CompanyRole, frozenset[AdminPanel]] = {
    CompanyRole.SERVICE_OPERATIONS_COORDINATOR: frozenset(
        {
            AdminPanel.ROSTER,
            AdminPanel.VISIT_BOARD,
            AdminPanel.MASTER_DATA,
            AdminPanel.MICROMARKET_PLANOGRAMS,
        }
    ),
    CompanyRole.PLANOGRAM_CURATOR: frozenset(
        {
            AdminPanel.DOMAIN_PRODUCTS,
            AdminPanel.MICROMARKET_PLANOGRAMS,
        }
    ),
    CompanyRole.COFFEE_TECHNOLOGIST: frozenset({AdminPanel.COFFEE_RECIPES}),
    CompanyRole.SETTLEMENT_OPERATOR: frozenset({AdminPanel.SETTLEMENT_ANALYSIS}),
    CompanyRole.PRICING_POLICY_HOLDER: frozenset({AdminPanel.MATRIX_PRICING}),
    CompanyRole.FIELD_TECHNICIAN: frozenset(),
}


@beartype
def panels_for_roles(roles: frozenset[CompanyRole] | set[CompanyRole]) -> frozenset[AdminPanel]:
    panels: set[AdminPanel] = set()
    for role in roles:
        if role is CompanyRole.ACCESS_ADMINISTRATOR:
            panels.update(permission_panels())
            continue
        panels.update(_ROLE_PANELS.get(role, frozenset()))
    return frozenset(panels)


@beartype
def has_access_administrator(roles: frozenset[CompanyRole] | set[CompanyRole]) -> bool:
    return CompanyRole.ACCESS_ADMINISTRATOR in roles


@beartype
def company_roles_from_legacy_panels(
    panels: frozenset[AdminPanel] | set[AdminPanel],
) -> frozenset[CompanyRole]:
    """Deterministic cutover: users/full set → access admin; else exact role covers."""
    panel_set = frozenset(panels)
    if not panel_set:
        return frozenset()
    all_panels = frozenset(permission_panels())
    if AdminPanel.USERS in panel_set or panel_set == all_panels:
        return frozenset({CompanyRole.ACCESS_ADMINISTRATOR})
    remaining = set(panel_set)
    roles: set[CompanyRole] = set()
    for role, role_panels in _ROLE_PANELS.items():
        if not role_panels:
            continue
        if role_panels <= remaining:
            roles.add(role)
            remaining -= set(role_panels)
    return frozenset(roles)


@beartype
@dataclass(frozen=True, slots=True)
class SystemUserId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("SystemUserId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class SystemUser:
    user_id: SystemUserId
    name: str
    role: BotRole
    is_active: bool
    telegram_user_id: int
    technician_id: TechnicianId | None
    company_roles: frozenset[CompanyRole]

    @property
    def panels(self) -> frozenset[AdminPanel]:
        return panels_for_roles(self.company_roles)

    @property
    def status_label_ru(self) -> str:
        return "активен" if self.is_active else "неактивен"

    @property
    def profile_line_ru(self) -> str:
        return f"{self.name} · {self.role.label_ru} · {self.status_label_ru}"
