from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    MachineKind,
    MachineStatus,
    SystemUserRecord,
)
from src.application.master_data.models import MasterMachine
from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.micromarket_loading import MicromarketDeviceStockStore
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG, auth_date: str | None = None) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())) if auth_date is None else auth_date,
    }
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    return fields


def _empty_user_store() -> InMemorySystemUserStore:
    return InMemorySystemUserStore()


def _build_app(
    *,
    machine_kind: MachineKind = MachineKind.MICRO_MARKET,
    machine_id: str = "701",
    panels: frozenset[AdminPanel] | None = None,
    micromarket_stock_store: MicromarketDeviceStockStore | None = None,
    domain_product_store: DomainProductStore | None = None,
    catalog_product_lookup: CatalogProductLookup | None = None,
    layout_master_enabled: bool = False,
    snack_layout_store: SnackMachineLayoutStore | None = None,
    attach_micromarket_planogram: bool = True,
) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
            ["u1", "Ops", "администратор", str(_ADMIN_TG), "", "да"],
        ],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId(machine_id),
            kind=machine_kind,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        ),
    )
    users_enabled = False
    system_user_store: InMemorySystemUserStore | None = None
    if panels is not None:
        user = SystemUser(
            user_id=SystemUserId(str(_ADMIN_TG)),
            name="Ops",
            role=BotRole.ADMINISTRATOR,
            is_active=True,
            telegram_user_id=_ADMIN_TG,
            technician_id=None,
            company_roles=company_roles_for_test_panels(panels),
        )
        provider.apply_system_users_snapshot(
            SystemUsersSnapshot(
                users_by_telegram_id={_ADMIN_TG: user},
                users_by_technician_id={},
            )
        )
        system_user_store = InMemorySystemUserStore()
        system_user_store.replace_all(
            (
                SystemUserRecord(
                    user=user,
                    updated_at=_FROZEN_NOW,
                    updated_by_telegram_user_id=_ADMIN_TG,
                ),
            )
        )
        users_enabled = True
    planogram_store = InMemoryMicromarketPlanogramStore() if attach_micromarket_planogram else None
    deps = AdminHttpDeps(
        provider=provider,
        roster_store=roster_store,
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token=_BOT_TOKEN,
        session_secret=_SESSION_SECRET,
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=False,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=master_stores,
        users_enabled=users_enabled,
        system_user_store=system_user_store,
        micromarket_planogram_store=planogram_store,
        micromarket_stock_store=micromarket_stock_store,
        domain_product_store=domain_product_store,
        catalog_product_lookup=catalog_product_lookup,
        layout_master_enabled=layout_master_enabled,
        snack_layout_store=snack_layout_store,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def _client(panels: frozenset[AdminPanel]) -> TestClient:
    app, deps = _build_app(
        panels=panels,
        machine_id="701",
        machine_kind=MachineKind.MICRO_MARKET,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
    )
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("501"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    return client


def test_keeper_forbidden_on_planogram_loading_products_and_layout() -> None:
    # После OM: MASTER_DATA → coordinator (+ micromarket_planograms).
    # «Keeper без планограммы» больше не моделируется одной панелью MASTER_DATA.
    coordinator = _client(frozenset({AdminPanel.MASTER_DATA}))
    assert coordinator.get("/admin/micromarket-planograms").status_code == 200
    assert coordinator.get("/admin/machines").status_code == 200
    assert coordinator.get("/admin/machines/701").status_code == 200
    # Куратор планограмм без парка — domain_products+planograms, без MASTER_DATA.
    curator_only = _client(frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    assert curator_only.get("/admin/micromarket-planograms").status_code == 200
    assert curator_only.get("/admin/machines").status_code == 403


def test_operator_opens_planogram_products_layout_and_not_park() -> None:
    # v1: planogram_curator → micromarket_planograms + domain_products; park нет
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    assert client.get("/admin/machines").status_code == 403
    assert client.get("/admin/machines/701").status_code == 403
    assert client.get("/admin/micromarket-planograms").status_code == 200
    assert client.get("/admin/machines/701/micromarket-planogram").status_code == 200
    assert client.get("/admin/domain-products").status_code == 200
    assert client.get("/admin/snack-planograms/501").status_code == 200
    loading = client.get("/admin/machines/701/micromarket-loading")
    assert loading.status_code == 200


def test_domain_products_panel_opens_products_and_planograms() -> None:
    # v1: одна роль куратора открывает оба экрана
    client = _client(frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    assert client.get("/admin/domain-products").status_code == 200
    assert client.get("/admin/micromarket-planograms").status_code == 200
    products = client.get("/admin/domain-products")
    assert 'href="/admin/domain-products"' in products.text
    assert ">Товары<" in products.text


def test_planogram_role_derives_products_and_planogram_panels() -> None:
    from src.domain.system_user import CompanyRole, panels_for_roles, permission_panels

    panels = panels_for_roles({CompanyRole.PLANOGRAM_CURATOR})
    assert AdminPanel.MICROMARKET_PLANOGRAMS in panels
    assert AdminPanel.DOMAIN_PRODUCTS in panels
    assert AdminPanel.DOMAIN_PRODUCTS in permission_panels()


def _panel_open_tag(html: str, tab: str) -> str:
    match = re.search(
        rf'<div class="admin-workspace-panel"[^>]*data-tab="{tab}"[^>]*>',
        html,
    )
    assert match is not None, tab
    return match.group(0)


def _panel_html(html: str, tab: str) -> str:
    marker = f'<div class="admin-workspace-panel" data-tab="{tab}"'
    start = html.find(marker)
    assert start != -1, tab
    rest = html[start:]
    next_panel = rest.find('<div class="admin-workspace-panel"', len(marker))
    if next_panel == -1:
        return rest
    return rest[:next_panel]


def test_fridge_workspace_shows_both_tabs_under_code() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    text = response.text
    assert text.count("<h1>") == 1
    assert "<h1>[склад] 701</h1>" in text
    assert ">Планограмма</button>" in text
    assert ">Сборка</button>" in text
    assert ">Загрузка</button>" in text
    assert ">Задачи аппарата</button>" in text
    assert 'href="/admin/micromarket-planograms">← Холодильники</a>' in text
    assert 'id="micromarket-planogram-form"' in text
    assert 'id="micromarket-assembly-form"' in text
    assert "hidden" not in _panel_open_tag(text, "planogram")
    assert "hidden" in _panel_open_tag(text, "assembly")
    assert "hidden" in _panel_open_tag(text, "loading")
    assert "hidden" in _panel_open_tag(text, "tasks")
    assert 'data-tab="tasks"' in text
    tab_buttons = re.findall(r'<button[^>]*class="admin-workspace-tab"[^>]*>', text)
    assert len(tab_buttons) == 4
    assert all("href" not in button for button in tab_buttons)
    inline_scripts = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
        text,
        flags=re.DOTALL,
    )
    assert inline_scripts
    # Loading/tasks need server round-trip (warehouse / journal); assign, not href jump.
    assert all("location.href" not in script for script in inline_scripts)
    assert any("location.assign" in script for script in inline_scripts)
    assert "admin-save-bar" in _panel_html(text, "planogram")
    assert "admin-save-bar" in _panel_html(text, "assembly")
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert ".admin-workspace-panel[hidden]" in css
    hidden_rule = css.split(".admin-workspace-panel[hidden]", 1)[1]
    hidden_rule = hidden_rule.split("}", 1)[0]
    assert "display: none" in hidden_rule


def test_fridge_workspace_query_selects_loading_tab() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    response = client.get("/admin/micromarket-planograms/701?tab=loading")
    assert response.status_code == 200
    text = response.text
    assert text.count("<h1>") == 1
    assert "<h1>[склад] 701</h1>" in text
    assert "hidden" in _panel_open_tag(text, "planogram")
    assert "hidden" not in _panel_open_tag(text, "loading")


def test_fridge_workspace_snack_or_missing_is_404() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    assert client.get("/admin/micromarket-planograms/501").status_code == 404
    assert client.get("/admin/micromarket-planograms/999").status_code == 404


def test_old_fridge_gets_redirect_after_panel_check() -> None:
    operator = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    planogram = operator.get(
        "/admin/machines/701/micromarket-planogram",
        follow_redirects=False,
    )
    assert planogram.status_code == 303
    assert planogram.headers["location"].endswith("/admin/micromarket-planograms/701")
    loading = operator.get(
        "/admin/machines/701/micromarket-loading",
        follow_redirects=False,
    )
    assert loading.status_code == 303
    assert loading.headers["location"].endswith("/admin/micromarket-planograms/701?tab=assembly")
    # Без панели: не логинимся — 303 на login, не 403.
    app, _deps = _build_app(
        panels=None,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
    )
    anon = TestClient(app)
    for path in (
        "/admin/machines/701/micromarket-planogram",
        "/admin/machines/701/micromarket-loading",
        "/admin/micromarket-planograms/701",
    ):
        response = anon.get(path, follow_redirects=False)
        assert response.status_code == 303, path


def test_fridge_post_returns_to_workspace() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import UUID

    from tests.interfaces.admin.test_micromarket_loading_routes import (
        _build_app_with_micromarket_loading_preview,
        _MemoryCycleStore,
    )
    from tests.interfaces.admin.test_micromarket_planogram_routes import (
        _build_app_with_micromarket_planogram,
    )

    from src.application.micromarket_loading.warehouse_stock_snapshot import (
        MainWarehouseStockSnapshot,
    )
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketWarehouseStockSnapshotStore,
    )

    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
            qty_by_catalog_code={"2311": Decimal("10")},
        ),
    )
    loading_app, _loading_deps = _build_app_with_micromarket_loading_preview(
        cycle_store=_MemoryCycleStore(),
        warehouse_stock_snapshot=stock,
    )
    loading_client = TestClient(loading_app)
    loading_client.post("/admin/auth/telegram", data=_signed_widget_fields())
    created = loading_client.post(
        "/admin/machines/701/micromarket-assembly-orders",
        data={
            "product_code": "2311",
            "assembly_qty": "2",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "/admin/micromarket-planograms/701?tab=loading" in created.headers["location"]

    planogram_app, _planogram_deps = _build_app_with_micromarket_planogram()
    planogram_client = TestClient(planogram_app)
    planogram_client.post("/admin/auth/telegram", data=_signed_widget_fields())
    saved = planogram_client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "active-0": "on",
            "kit_group_id-0": "6348",
            "shelf_kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"].endswith("/admin/micromarket-planograms/701")
    assert not saved.headers["location"].endswith("?tab=loading")
