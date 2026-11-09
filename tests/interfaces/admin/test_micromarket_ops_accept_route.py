from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal
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
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import MachineId
from src.domain.micromarket_loading.assembly_order import (
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
    panels_for_roles,
)
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketAssemblyOrderStore,
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.routes.micromarket_loading import _company_roles_may_ops_accept

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def test_ops_accept_admin_post_requires_coordinator() -> None:
    """error: planogram curator alone cannot ops-accept; coordinator can."""
    curator = frozenset({CompanyRole.PLANOGRAM_CURATOR})
    coordinator = frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR})
    assert _company_roles_may_ops_accept(curator) is False
    assert _company_roles_may_ops_accept(coordinator) is True
    assert AdminPanel.MICROMARKET_PLANOGRAMS in panels_for_roles(coordinator)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())),
    }
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    return fields


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


def _seed_open_loading(cycle_store: _MemoryCycleStore) -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=5,
                stock_qty=Decimal("2"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        )
    )
    cycle.open_order(
        order_id="ord-fm-1",
        move_id="mv-fm-1",
        lines=cycle.lines,
        opened_at=_FROZEN_NOW,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )
    cycle.pull_events()
    cycle_store.save(cycle)
    assert cycle.status is OrderStatus.OPEN


def _build_client(
    *,
    panels: frozenset[AdminPanel],
    cycle_store: _MemoryCycleStore | None = None,
    assembly_store: InMemoryMicromarketAssemblyOrderStore | None = None,
) -> TestClient:
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
    master_stores = InMemoryMasterDataStores()
    master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("701"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        ),
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
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
        users_enabled=True,
        system_user_store=system_user_store,
        micromarket_planogram_store=InMemoryMicromarketPlanogramStore(),
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        micromarket_loading_cycle_store=(
            cycle_store if cycle_store is not None else _MemoryCycleStore()
        ),
        micromarket_assembly_order_store=(
            assembly_store
            if assembly_store is not None
            else InMemoryMicromarketAssemblyOrderStore()
        ),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    return client


def test_fm_tab_visible_only_for_coordinator() -> None:
    """happy: coordinator sees FM tab; curator does not."""
    coordinator = _build_client(panels=frozenset({AdminPanel.MASTER_DATA}))
    page = coordinator.get("/admin/micromarket-planograms/701")
    assert page.status_code == 200
    assert 'data-tab="fm"' in page.text
    assert ">FM</button>" in page.text

    curator = _build_client(panels=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    curator_page = curator.get("/admin/micromarket-planograms/701")
    assert curator_page.status_code == 200
    assert 'data-tab="fm"' not in curator_page.text
    assert ">FM</button>" not in curator_page.text


def test_fm_tab_button_disabled_without_open_orders() -> None:
    """edge: FM button disabled when no open loading and no assembly orders."""
    client = _build_client(panels=frozenset({AdminPanel.MASTER_DATA}))
    page = client.get("/admin/micromarket-planograms/701?tab=fm")
    assert page.status_code == 200
    assert 'id="micromarket-ops-accept-form"' in page.text
    assert "Подтвердить загрузку без пересчёта" in page.text
    button_chunk = page.text.split("micromarket-ops-accept-form", 1)[1].split("</button>", 1)[0]
    assert "disabled" in button_chunk


def test_fm_tab_button_enabled_with_open_loading_order() -> None:
    """happy: open loading order enables ops-accept button on FM tab."""
    cycle_store = _MemoryCycleStore()
    _seed_open_loading(cycle_store)
    client = _build_client(
        panels=frozenset({AdminPanel.MASTER_DATA}),
        cycle_store=cycle_store,
    )
    page = client.get("/admin/micromarket-planograms/701?tab=fm")
    assert page.status_code == 200
    assert 'form="micromarket-ops-accept-form"' in page.text
    assert "disabled" not in page.text.split("micromarket-ops-accept-form", 1)[1].split(
        "</button>", 1
    )[0]


def test_fm_tab_button_enabled_with_open_assembly_orders() -> None:
    """happy: open assembly order alone enables the FM button."""
    assembly = InMemoryMicromarketAssemblyOrderStore()
    assembly.save(
        MicromarketAssemblyOrder(
            order_id="asm-fm-1",
            machine_code="701",
            lines=(MicromarketAssemblyOrderLine(catalog_code="2311", qty=Decimal("2")),),
            created_at=_FROZEN_NOW,
        )
    )
    client = _build_client(
        panels=frozenset({AdminPanel.MASTER_DATA}),
        assembly_store=assembly,
    )
    page = client.get("/admin/micromarket-planograms/701?tab=fm")
    assert page.status_code == 200
    button_chunk = page.text.split("micromarket-ops-accept-form", 1)[1].split("</button>", 1)[0]
    assert "disabled" not in button_chunk


def test_ops_accept_post_forbidden_for_curator() -> None:
    """error: curator POST ops-accept → 403."""
    cycle_store = _MemoryCycleStore()
    _seed_open_loading(cycle_store)
    client = _build_client(
        panels=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}),
        cycle_store=cycle_store,
    )
    response = client.post(
        "/admin/machines/701/micromarket-loading/ops-accept",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_ops_accept_post_redirects_to_fm_tab() -> None:
    """happy: coordinator ops-accept redirects to FM tab and closes order."""
    cycle_store = _MemoryCycleStore()
    _seed_open_loading(cycle_store)
    client = _build_client(
        panels=frozenset({AdminPanel.MASTER_DATA}),
        cycle_store=cycle_store,
    )
    response = client.post(
        "/admin/machines/701/micromarket-loading/ops-accept",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "/admin/micromarket-planograms/701?tab=fm"
    )
    saved = cycle_store.load("701")
    assert saved is not None
    assert saved.status is OrderStatus.CLOSED


def test_curator_assembly_tab_has_no_ops_accept_button() -> None:
    """edge: curator assembly tab must not render ops-accept control."""
    client = _build_client(panels=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    page = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert page.status_code == 200
    assert "micromarket-ops-accept-form" not in page.text
    assert "Подтвердить загрузку без пересчёта" not in page.text
