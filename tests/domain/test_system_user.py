from __future__ import annotations

import pytest

from src.domain.system_user import (
    NAV_ALIAS_PANELS,
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
    panels_for_roles,
    permission_panels,
)


def test_system_user_profile_line_unchanged() -> None:
    user = SystemUser(
        user_id=SystemUserId("u1"),
        name="Иван",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1001,
        technician_id=None,
        company_roles=frozenset(),
    )
    assert user.profile_line_ru == "Иван · Администратор · активен"
    assert BotRole.TECHNICIAN.label_ru == "Техник"


def test_system_user_id_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SystemUserId("")


def test_bot_role_none_label_ru() -> None:
    assert BotRole.NONE.value == "none"
    assert BotRole.NONE.label_ru == "Нет доступа к боту"


def test_admin_panel_values() -> None:
    assert {p.value for p in AdminPanel} == {
        "roster",
        "master_data",
        "users",
        "visit_board",
        "visit_photo_review",
        "settlement_analysis",
        "matrix_pricing",
        "matrix_sku_catalog",
        "micromarket_planograms",
        "technicians",
        "companies",
        "domain_products",
        "coffee_recipes",
        "nav_settings",
    }


def test_admin_panel_includes_visit_board() -> None:
    assert {p.value for p in AdminPanel} == {
        "roster",
        "master_data",
        "users",
        "visit_board",
        "visit_photo_review",
        "settlement_analysis",
        "matrix_pricing",
        "matrix_sku_catalog",
        "micromarket_planograms",
        "technicians",
        "companies",
        "domain_products",
        "coffee_recipes",
        "nav_settings",
    }
    assert AdminPanel.VISIT_BOARD is AdminPanel("visit_board")


def test_admin_panel_includes_visit_photo_review() -> None:
    assert AdminPanel.VISIT_PHOTO_REVIEW.value == "visit_photo_review"
    assert AdminPanel.VISIT_PHOTO_REVIEW in permission_panels()
    assert AdminPanel.VISIT_PHOTO_REVIEW not in NAV_ALIAS_PANELS


def test_admin_panel_includes_settlement_analysis() -> None:
    assert AdminPanel.SETTLEMENT_ANALYSIS.value == "settlement_analysis"
    assert AdminPanel.SETTLEMENT_ANALYSIS in frozenset(AdminPanel)


def test_admin_panel_includes_nav_settings() -> None:
    assert AdminPanel.NAV_SETTINGS.value == "nav_settings"
    assert AdminPanel("nav_settings") is AdminPanel.NAV_SETTINGS


def test_admin_panel_has_matrix_pricing() -> None:
    assert AdminPanel.MATRIX_PRICING.value == "matrix_pricing"


def test_system_user_panels_derived_from_company_roles() -> None:
    user = SystemUser(
        user_id=SystemUserId("u1"),
        name="Оп",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1,
        technician_id=None,
        company_roles=frozenset(
            {
                CompanyRole.SETTLEMENT_OPERATOR,
                CompanyRole.PRICING_POLICY_HOLDER,
            }
        ),
    )
    assert user.panels == frozenset({AdminPanel.SETTLEMENT_ANALYSIS, AdminPanel.MATRIX_PRICING})
    assert user.company_roles == frozenset(
        {
            CompanyRole.SETTLEMENT_OPERATOR,
            CompanyRole.PRICING_POLICY_HOLDER,
        }
    )


def test_company_role_label_ru_matches_v1_table() -> None:
    assert CompanyRole.ACCESS_ADMINISTRATOR.label_ru == "Администратор доступа"
    assert CompanyRole.SERVICE_OPERATIONS_COORDINATOR.label_ru == "Координатор сервисных операций"
    assert CompanyRole.PLANOGRAM_CURATOR.label_ru == "Куратор планограмм и товарной идентичности"
    assert CompanyRole.COFFEE_TECHNOLOGIST.label_ru == "Технолог"
    assert CompanyRole.SETTLEMENT_OPERATOR.label_ru == "Оператор сверки"
    assert CompanyRole.PRICING_POLICY_HOLDER.label_ru == "Держатель ценовой политики"
    assert CompanyRole.FIELD_TECHNICIAN.label_ru == "Полевой техник"


def test_panels_for_roles_unions_two_roles() -> None:
    panels = panels_for_roles(
        {
            CompanyRole.SETTLEMENT_OPERATOR,
            CompanyRole.SERVICE_OPERATIONS_COORDINATOR,
        }
    )
    assert panels == frozenset(
        {
            AdminPanel.SETTLEMENT_ANALYSIS,
            AdminPanel.ROSTER,
            AdminPanel.VISIT_BOARD,
            AdminPanel.MASTER_DATA,
            AdminPanel.MICROMARKET_PLANOGRAMS,
        }
    )


def test_panels_for_roles_access_administrator_gets_all_permission_panels() -> None:
    assert panels_for_roles({CompanyRole.ACCESS_ADMINISTRATOR}) == frozenset(permission_panels())


def test_panels_for_roles_pricing_policy_holder_gets_matrix_pricing() -> None:
    assert panels_for_roles({CompanyRole.PRICING_POLICY_HOLDER}) == frozenset(
        {AdminPanel.MATRIX_PRICING}
    )


def test_panels_for_roles_empty_and_field_technician_are_empty() -> None:
    assert panels_for_roles(frozenset()) == frozenset()
    assert panels_for_roles({CompanyRole.FIELD_TECHNICIAN}) == frozenset()


def test_company_role_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        CompanyRole("not_a_company_role")
