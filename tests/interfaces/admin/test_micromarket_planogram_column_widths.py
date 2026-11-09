from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores, MachineKind, MachineStatus
from src.application.master_data.models import MasterMachine
from src.application.micromarket_loading import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
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

_COLGROUP_RE = re.compile(
    r"<table class=\"admin-roster planogram-shelf-table\">\s*"
    r"<colgroup>\s*"
    r'<col class="planogram-col-product">\s*'
    r'<col class="planogram-col-target">\s*'
    r'<col class="planogram-col-stock">\s*'
    r'<col class="planogram-col-buy">\s*'
    r'<col class="planogram-col-price">\s*'
    r"</colgroup>",
    re.MULTILINE,
)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields() -> dict[str, str]:
    fields = {
        "id": str(_ADMIN_TG),
        "auth_date": str(int(_FROZEN_NOW.timestamp())),
    }
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    return fields


def _build_app() -> tuple[FastAPI, AdminHttpDeps]:
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
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["2311", "Салат Цезарь", "product"],
            ["2312", "Вода 0.5", "product"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("701"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        ),
    )
    planogram_store = InMemoryMicromarketPlanogramStore()
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
        users_enabled=False,
        micromarket_planogram_store=planogram_store,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def test_shelf_tables_share_colgroup_layout() -> None:
    # happy: shared colgroup/layout applied on every shelf table
    app, deps = _build_app()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    matches = _COLGROUP_RE.findall(response.text)
    assert len(matches) >= 2
    css = (
        __import__("pathlib")
        .Path("src/interfaces/admin/static/admin.css")
        .read_text(encoding="utf-8")
    )
    assert "table.planogram-shelf-table" in css
    assert "table-layout: fixed" in css
    assert "planogram-col-target" in css
    assert "planogram-col-stock" in css
    assert "planogram-col-buy" in css
    assert (
        re.search(
            r"col\.planogram-col-target\s*\{\s*width:\s*1[0-2]%",
            css,
        )
        is not None
    )
    assert (
        re.search(
            r"col\.planogram-col-buy\s*\{\s*width:\s*1[0-9]%",
            css,
        )
        is not None
    )
    assert re.search(
        r"table\.admin-roster th\b[^}]*text-align:\s*center",
        css,
        re.DOTALL,
    )


def test_single_shelf_still_has_shared_colgroup() -> None:
    # edge: single shelf unchanged contract — still has shared colgroup
    app, deps = _build_app()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "Основная"),)),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert _COLGROUP_RE.search(response.text) is not None
