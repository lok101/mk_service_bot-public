from __future__ import annotations

from src.application.shared.admin_nav import default_admin_nav_structure
from src.domain.system_user import (
    NAV_ALIAS_PANELS,
    PLANOGRAM_OPERATOR_NAV_PANELS,
    AdminPanel,
    permission_panels,
)


def test_domain_products_is_own_checkbox_panel() -> None:
    # happy — LOK-240: gate = sidebar panel = checkbox
    assert AdminPanel.DOMAIN_PRODUCTS.value == "domain_products"
    assert AdminPanel.DOMAIN_PRODUCTS not in NAV_ALIAS_PANELS
    assert AdminPanel.DOMAIN_PRODUCTS not in PLANOGRAM_OPERATOR_NAV_PANELS
    assert AdminPanel.DOMAIN_PRODUCTS in permission_panels()


def test_default_nav_includes_domain_products() -> None:
    structure = default_admin_nav_structure()
    folder = next(n for n in structure.nodes if getattr(n, "folder_id", None) == "directories")
    assert AdminPanel.DOMAIN_PRODUCTS in folder.children
    companies_idx = folder.children.index(AdminPanel.COMPANIES)
    assert folder.children.index(AdminPanel.DOMAIN_PRODUCTS) == companies_idx + 1
