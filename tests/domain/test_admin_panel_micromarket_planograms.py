from __future__ import annotations

from src.application.shared.admin_nav import default_admin_nav_structure
from src.domain.system_user import NAV_ALIAS_PANELS, AdminPanel, permission_panels


def test_micromarket_planograms_is_checkbox() -> None:
    assert AdminPanel.MICROMARKET_PLANOGRAMS.value == "micromarket_planograms"
    assert AdminPanel.MICROMARKET_PLANOGRAMS not in NAV_ALIAS_PANELS
    assert AdminPanel.MICROMARKET_PLANOGRAMS in permission_panels()


def test_sku_technicians_companies_are_own_checkboxes() -> None:
    assert AdminPanel.MATRIX_SKU_CATALOG not in NAV_ALIAS_PANELS
    assert AdminPanel.TECHNICIANS not in NAV_ALIAS_PANELS
    assert AdminPanel.COMPANIES not in NAV_ALIAS_PANELS
    assert AdminPanel.MATRIX_SKU_CATALOG in permission_panels()
    assert AdminPanel.TECHNICIANS in permission_panels()
    assert AdminPanel.COMPANIES in permission_panels()


def test_default_nav_includes_micromarket_planograms() -> None:
    structure = default_admin_nav_structure()
    folder = next(n for n in structure.nodes if getattr(n, "folder_id", None) == "directories")
    assert AdminPanel.MICROMARKET_PLANOGRAMS in folder.children
