from __future__ import annotations

from src.domain.system_user import (
    AdminPanel,
    CompanyRole,
    company_roles_from_legacy_panels,
    permission_panels,
)

_ADMIN_ONLY_PANELS = frozenset(
    {
        AdminPanel.USERS,
        AdminPanel.NAV_SETTINGS,
        AdminPanel.VISIT_PHOTO_REVIEW,
        AdminPanel.TECHNICIANS,
        AdminPanel.COMPANIES,
        AdminPanel.MATRIX_SKU_CATALOG,
    }
)
_SERVICE_PANELS = frozenset(
    {
        AdminPanel.ROSTER,
        AdminPanel.VISIT_BOARD,
        AdminPanel.MASTER_DATA,
    }
)
_PLANOGRAM_PANELS = frozenset(
    {
        AdminPanel.DOMAIN_PRODUCTS,
        AdminPanel.MICROMARKET_PLANOGRAMS,
    }
)


def company_roles_for_test_panels(
    panels: frozenset[AdminPanel] | set[AdminPanel],
) -> frozenset[CompanyRole]:
    """Map arbitrary test panel bags to company roles after LOK-243 cutover."""
    panel_set = frozenset(panels)
    if not panel_set:
        return frozenset()
    if AdminPanel.USERS in panel_set or panel_set >= frozenset(permission_panels()):
        return frozenset({CompanyRole.ACCESS_ADMINISTRATOR})
    migrated = company_roles_from_legacy_panels(panel_set)
    if migrated:
        return migrated
    if panel_set & _ADMIN_ONLY_PANELS:
        return frozenset({CompanyRole.ACCESS_ADMINISTRATOR})
    roles: set[CompanyRole] = set()
    if panel_set & _SERVICE_PANELS:
        roles.add(CompanyRole.SERVICE_OPERATIONS_COORDINATOR)
    if panel_set & _PLANOGRAM_PANELS:
        roles.add(CompanyRole.PLANOGRAM_CURATOR)
    if AdminPanel.COFFEE_RECIPES in panel_set:
        roles.add(CompanyRole.COFFEE_TECHNOLOGIST)
    if AdminPanel.SETTLEMENT_ANALYSIS in panel_set:
        roles.add(CompanyRole.SETTLEMENT_OPERATOR)
    if AdminPanel.MATRIX_PRICING in panel_set:
        roles.add(CompanyRole.PRICING_POLICY_HOLDER)
    return frozenset(roles)
