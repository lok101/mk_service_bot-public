from __future__ import annotations

from src.application.shared.admin_nav import default_admin_nav_structure
from src.domain.system_user import NAV_ALIAS_PANELS, AdminPanel, permission_panels


def test_companies_is_own_checkbox_panel() -> None:
    assert AdminPanel.COMPANIES.value == "companies"
    assert AdminPanel.COMPANIES not in NAV_ALIAS_PANELS
    assert AdminPanel.COMPANIES in permission_panels()


def test_default_nav_includes_companies_after_technicians() -> None:
    structure = default_admin_nav_structure()
    folder = next(n for n in structure.nodes if getattr(n, "folder_id", None) == "directories")
    assert AdminPanel.COMPANIES in folder.children
    tech_idx = folder.children.index(AdminPanel.TECHNICIANS)
    assert folder.children.index(AdminPanel.COMPANIES) == tech_idx + 1
