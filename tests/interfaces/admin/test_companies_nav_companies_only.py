from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.master_data import (
    CreateCompany,
    InMemoryCompanyStore,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
)
from src.application.reference_data import ReferenceDataProvider
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.system_users_view import (
    build_nav_tree_for_request,
    mounted_admin_panels,
)


def _flatten_panels(tree: object) -> list[AdminPanel]:
    panels: list[AdminPanel] = []
    for node in tree:  # type: ignore[union-attr]
        if node.kind == "panel":
            panels.append(node.panel)
        else:
            panels.extend(child.panel for child in node.children)
    return panels


def test_nav_tree_shows_companies_without_park_when_companies_only() -> None:
    create_company = CreateCompany(
        store=InMemoryCompanyStore(),
        counters=InMemoryMasterDataCounterStore(),
        audit=InMemoryMasterDataAuditStore(),
    )
    deps = AdminHttpDeps(
        provider=ReferenceDataProvider(),
        roster_store=InMemoryLocationRosterStore(),
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token="test-bot-token",
        session_secret="admin-session-secret",
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=True,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: datetime(2026, 9, 3, tzinfo=UTC),
        users_enabled=False,
        companies_enabled=True,
        create_company=create_company,
        master_stores=None,
        technicians_enabled=False,
    )
    mounted = mounted_admin_panels(deps)
    assert AdminPanel.COMPANIES in mounted
    assert AdminPanel.MASTER_DATA not in mounted
    tree = build_nav_tree_for_request(
        deps,
        telegram_user_id=1001,
        request_path="/admin/companies",
    )
    panels = _flatten_panels(tree)
    assert AdminPanel.COMPANIES in panels
    assert AdminPanel.MASTER_DATA not in panels
