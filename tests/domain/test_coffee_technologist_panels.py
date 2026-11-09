from __future__ import annotations

from src.domain.system_user import AdminPanel, CompanyRole, panels_for_roles, permission_panels


def test_coffee_technologist_gets_only_coffee_recipes() -> None:
    assert panels_for_roles({CompanyRole.COFFEE_TECHNOLOGIST}) == frozenset(
        {AdminPanel.COFFEE_RECIPES}
    )


def test_coffee_technologist_label_ru() -> None:
    assert CompanyRole.COFFEE_TECHNOLOGIST.label_ru == "Технолог"


def test_planogram_curator_does_not_include_coffee_recipes() -> None:
    panels = panels_for_roles({CompanyRole.PLANOGRAM_CURATOR})
    assert AdminPanel.COFFEE_RECIPES not in panels
    assert AdminPanel.DOMAIN_PRODUCTS in panels


def test_union_curator_and_technologist() -> None:
    panels = panels_for_roles(
        {
            CompanyRole.PLANOGRAM_CURATOR,
            CompanyRole.COFFEE_TECHNOLOGIST,
        }
    )
    assert AdminPanel.COFFEE_RECIPES in panels
    assert AdminPanel.DOMAIN_PRODUCTS in panels
    assert AdminPanel.MICROMARKET_PLANOGRAMS in panels


def test_access_administrator_includes_coffee_recipes() -> None:
    assert AdminPanel.COFFEE_RECIPES in panels_for_roles({CompanyRole.ACCESS_ADMINISTRATOR})
    assert AdminPanel.COFFEE_RECIPES in permission_panels()
