from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret-16"


@dataclass(frozen=True, slots=True)
class _FakeMsProduct:
    code: str
    name: str
    archived: bool = False


class _FakeSnackAssortmentReader:
    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[_FakeMsProduct]:
        return [_FakeMsProduct(code="1616", name="Чудо")]


def _build_app(
    *,
    stub: bool = True,
    admin_max_body_bytes: int = 32,
    with_master_stores: bool = False,
    sku_catalog_master_enabled: bool = False,
) -> FastAPI:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
            ["u1", "Ops", "администратор", "1001", "", "да"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores() if with_master_stores else None
    sku_store = InMemoryMatrixSkuCatalogStore() if sku_catalog_master_enabled else None
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
        stub_login_enabled=stub,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _NOW,
        admin_max_body_bytes=admin_max_body_bytes,
        master_stores=master_stores,
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        matrix_sku_catalog_store=sku_store,
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader()
        if sku_catalog_master_enabled
        else None,
        snack_sku_folder_ids=(
            (UUID("11111111-1111-1111-1111-111111111111"),) if sku_catalog_master_enabled else ()
        ),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app


def _stub_session(client: TestClient) -> None:
    session = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": "1001"},
        follow_redirects=False,
    )
    assert session.status_code in {200, 303, 302}


def test_admin_post_oversized_body_returns_413() -> None:
    client = TestClient(_build_app(stub=True, admin_max_body_bytes=32))
    _stub_session(client)
    response = client.post(
        "/admin/roster/draft",
        data="x" * 64,
        cookies=client.cookies,
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 413


def test_admin_matrix_sku_bulk_save_oversized_body_returns_413() -> None:
    client = TestClient(
        _build_app(
            stub=True,
            admin_max_body_bytes=32,
            with_master_stores=True,
            sku_catalog_master_enabled=True,
        )
    )
    _stub_session(client)
    response = client.post(
        "/admin/matrix-sku-catalog",
        data="x" * 64,
        cookies=client.cookies,
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 413


def test_admin_machine_profile_post_oversized_body_returns_413() -> None:
    client = TestClient(
        _build_app(
            stub=True,
            admin_max_body_bytes=32,
            with_master_stores=True,
        )
    )
    _stub_session(client)
    response = client.post(
        "/admin/machines/101",
        data="x" * 64,
        cookies=client.cookies,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "http://testserver",
        },
    )
    assert response.status_code == 413


def test_admin_rejects_oversized_content_length_header() -> None:
    client = TestClient(_build_app(stub=True, admin_max_body_bytes=32))
    response = client.post(
        "/admin/auth/stub",
        content=b"tiny",
        headers={"Content-Length": "999999"},
    )
    assert response.status_code == 413
