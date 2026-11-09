from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import unquote
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
)
from src.application.matrix_automation import (
    ApplySnackMatrix,
    BuildMatrixDeployResult,
    InMemorySnackMachineLayoutStore,
    MatrixDeployPayload,
    MatrixDeployResult,
    PriceSnapshotDocument,
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.matrix_automation.snack_planogram import SnackPlanogramMerge
from src.application.product_identity import (
    CatalogProduct,
    create_domain_product,
    link_domain_product,
)
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.infrastructure.matrix_automation.memory_snapshots import InMemoryMatrixPriceSnapshotStore
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import _refresh_provider_master_data, register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeMsProduct:
    code: str
    name: str
    archived: bool = False


class _FakeSnackAssortmentReader:
    def __init__(
        self,
        items: dict[str, str],
        *,
        archived_codes: frozenset[str] | set[str] = frozenset(),
        fail: bool = False,
    ) -> None:
        self._items = items
        self._archived_codes = frozenset(archived_codes)
        self._fail = fail

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[_FakeMsProduct]:
        if self._fail:
            raise RuntimeError("ms unavailable")
        return [
            _FakeMsProduct(
                code=code,
                name=name,
                archived=code in self._archived_codes,
            )
            for code, name in self._items.items()
        ]


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


def _admin_rows(
    *,
    role: str = "администратор",
    active: str = "да",
    tg: int = _ADMIN_TG,
) -> list[list[str]]:
    return [
        ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
        ["u1", "Ops", role, str(tg), "", active],
    ]


@dataclass(slots=True)
class _FakeStock:
    _qty: Decimal = Decimal("0")
    _product: str | None = None

    def qty(self, machine_code: str, logical_matrix_name: str, line_number: int) -> Decimal:
        del machine_code, logical_matrix_name, line_number
        return self._qty

    def product(self, machine_code: str, logical_matrix_name: str, line_number: int) -> str | None:
        del machine_code, logical_matrix_name, line_number
        return self._product


@dataclass(slots=True)
class _FakeSnackStockStore:
    by_code: dict[str, _FakeStock] = field(default_factory=dict)

    def load(self, machine_code: str) -> _FakeStock | None:
        return self.by_code.get(machine_code)

    def save(self, stock: object) -> None:
        del stock


class _ApplyDeployer:
    def deploy(self, payloads: list[object]) -> list[MatrixDeployResult]:
        payload = payloads[0]
        assert isinstance(payload, MatrixDeployPayload)
        return [
            MatrixDeployResult(
                logical_matrix_name=payload.logical_matrix_name,
                machine_code=payload.machine_code,
                status="applied",
                reason=None,
            )
        ]


class _ApplyJobs:
    def insert(self, job: object) -> None:
        del job

    def finalize(self, job: object) -> None:
        del job


class _ApplyClock:
    def now_utc_iso(self) -> str:
        return "2026-08-28T00:00:00Z"


def _ok_apply_build(state: object, **kwargs: object) -> BuildMatrixDeployResult:
    from src.application.matrix_automation.models import MatrixParseState

    del kwargs
    assert isinstance(state, MatrixParseState)
    matrix = state.enabled_matrices[0]
    machine_code = matrix.machine_codes[0]
    return BuildMatrixDeployResult(
        payloads=(
            MatrixDeployPayload(
                logical_matrix_name=matrix.logical_matrix_name,
                machine_code=machine_code,
                matrix_multiplier="1.0",
                lines=(),
            ),
        ),
        skipped_units=(),
    )


def _build_apply_use_case(
    *,
    layouts: InMemorySnackMachineLayoutStore,
    snapshots: InMemoryMatrixPriceSnapshotStore,
    margin_store: InMemoryMatrixBaseMarginStore,
    run_build: object = _ok_apply_build,
    products: DomainProductStore | None = None,
) -> ApplySnackMatrix:
    return ApplySnackMatrix(
        layouts=layouts,
        base_margin_store=margin_store,
        snapshots=snapshots,
        deployer=_ApplyDeployer(),
        run_build=run_build,  # type: ignore[arg-type]
        job_repository=_ApplyJobs(),
        clock=_ApplyClock(),
        id_factory=lambda: "apply-job",
        products=products,
    )


def _build_app(
    *,
    layout_master_enabled: bool = True,
    with_master_panel: bool = True,
    sku_catalog_master_enabled: bool = False,
    matrix_sku_catalog_store: InMemoryMatrixSkuCatalogStore | None = None,
    snack_sku_assortment_reader: _FakeSnackAssortmentReader | None = None,
    snack_sku_folder_ids: tuple[str, ...] = (),
    with_base_margin: bool = True,
    admin_max_body_bytes: int = 1_048_576,
    domain_product_store: DomainProductStore | None = None,
) -> tuple[FastAPI, AdminHttpDeps, InMemorySnackMachineLayoutStore, _FakeSnackStockStore]:
    provider = ReferenceDataProvider()
    role = "администратор" if with_master_panel else "техник"
    tg = _ADMIN_TG if with_master_panel else _TECH_TG
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            *_admin_rows(role=role, tg=tg),
            ["u2", "Иван", "техник", "3003", "001", "да"],
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
            ["NEW", "New Product", "product"],
            ["OLD", "Old Product", "product"],
            ["A", "Product A", "product"],
            ["B", "Product B", "product"],
            ["NOT_READY", "Not Ready", "product"],
            ["READY", "Ready Product", "product"],
            ["2311", "Салат", "product"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    layouts = InMemorySnackMachineLayoutStore()
    snapshots = InMemoryMatrixPriceSnapshotStore()
    stock_store = _FakeSnackStockStore()
    margin_store = InMemoryMatrixBaseMarginStore()
    if with_base_margin:
        margin_store.save(curved_margin_params())
    apply_snack_matrix = _build_apply_use_case(
        layouts=layouts,
        snapshots=snapshots,
        margin_store=margin_store,
        products=domain_product_store,
    )
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
        admin_max_body_bytes=admin_max_body_bytes,
        master_stores=master_stores,
        layout_master_enabled=layout_master_enabled,
        snack_layout_store=layouts,
        matrix_price_snapshot_store=snapshots,
        snack_stock_store=stock_store,
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        matrix_sku_catalog_store=matrix_sku_catalog_store if sku_catalog_master_enabled else None,
        snack_sku_assortment_reader=snack_sku_assortment_reader,
        snack_sku_folder_ids=snack_sku_folder_ids,
        matrix_base_margin_store=margin_store,
        apply_snack_matrix=apply_snack_matrix,
        domain_product_store=domain_product_store,
        catalog_product_lookup=(
            FakeCatalogLookup(()) if domain_product_store is not None else None
        ),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, layouts, stock_store


def _authed_client(app: FastAPI, *, tg: int = _ADMIN_TG) -> TestClient:
    client = TestClient(app)
    if tg == _ADMIN_TG:
        client.post("/admin/auth/telegram", data=_signed_widget_fields())
    else:
        token = pack_admin_session(
            telegram_user_id=tg,
            issued_at=int(_FROZEN_NOW.timestamp()),
            secret=_SESSION_SECRET,
        )
        client.cookies.set(admin_session_cookie_name(), token)
    return client


def _seed_machine(deps: AdminHttpDeps, *, kind: MachineKind) -> MachineId:
    assert deps.master_stores is not None
    InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: _FROZEN_NOW,
    ).execute(
        InstallMachineAtLocationInput(
            name="Точка",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=kind,
            actor_telegram_user_id=_ADMIN_TG,
        )
    )
    machines = [m for m in deps.master_stores.machines.list_all() if m.kind is kind]
    assert machines
    return machines[-1].machine_id


def seed_coffee(deps: AdminHttpDeps) -> MachineId:
    return _seed_machine(deps, kind=MachineKind.COFFEE)


def seed_snack_with_layout(
    deps: AdminHttpDeps,
    layouts: InMemorySnackMachineLayoutStore,
    *,
    line: int,
    product: str,
) -> MachineId:
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    code = machine_id.value
    layouts.upsert(
        SnackMachineLayout(
            machine_code=code,
            logical_matrix_name=f"M{code}",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(line, product),),
        )
    )
    return machine_id


def _layout_path(machine_id: str | MachineId) -> str:
    mid = machine_id.value if isinstance(machine_id, MachineId) else machine_id
    return f"/admin/machines/{mid}/layout"


def _snack_workspace_path(machine_id: str | MachineId) -> str:
    mid = machine_id.value if isinstance(machine_id, MachineId) else machine_id
    return f"/admin/snack-planograms/{mid}"


def _planogram_post(
    *,
    shelf_count: int = 6,
    slots_per_shelf: int = 10,
    anchors: list[tuple[int, int, str, str, str]] | None = None,
    merges: list[tuple[int, int]] | None = None,
    auto_sync_enabled: bool = False,
) -> dict[str, object]:
    """anchors: shelf, slot, line, code, name."""
    data: dict[str, object] = {
        "layout_section": "1",
        "matrix_multiplier": "1",
        "planogram_shelf_count": str(shelf_count),
        "planogram_slots_per_shelf": str(slots_per_shelf),
    }
    if auto_sync_enabled:
        data["auto_sync_enabled"] = "on"
    for shelf, slot, line, code, name in anchors or ():
        data.setdefault("planogram_shelf_index", []).append(str(shelf))
        data.setdefault("planogram_slot_index", []).append(str(slot))
        data.setdefault("planogram_line_number", []).append(line)
        data.setdefault("planogram_product_code", []).append(code)
        data.setdefault("planogram_product_name", []).append(name)
    for shelf, slot in merges or ():
        data.setdefault("planogram_merge_shelf", []).append(str(shelf))
        data.setdefault("planogram_merge_slot", []).append(str(slot))
    return data


def _seed_unit_snapshot(
    snapshots: InMemoryMatrixPriceSnapshotStore,
    *,
    machine_code: str,
    logical_matrix_name: str,
) -> None:
    snapshots.save(
        PriceSnapshotDocument(
            job_id="test-job",
            machine_code=machine_code,
            logical_matrix_name=logical_matrix_name,
            recorded_at="2026-08-24T12:00:00Z",
            lines=(),
        )
    )


def test_machine_profile_shows_review_participation_checkbox() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.get(f"/admin/machines/{snack_id.value}")
    assert response.status_code == 200
    assert "Участвует в разборе фото" in response.text
    assert 'name="include_in_visit_photo_review"' in response.text


def test_machine_profile_post_clears_review_participation_when_unchecked() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    assert deps.master_stores is not None
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        data={
            "include_in_no_sales_monitoring": "on",
            "create_visit_on_no_sales": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    machine = deps.master_stores.machines.get(snack_id)
    assert machine is not None
    assert machine.include_in_no_sales_monitoring is True
    assert machine.create_visit_on_no_sales is True
    assert machine.include_in_visit_photo_review is False


def test_machine_profile_post_hydrates_provider_after_durable_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def recording_refresh(deps: AdminHttpDeps) -> None:
        calls.append("hydrate")
        _refresh_provider_master_data(deps)

    monkeypatch.setattr(
        "src.interfaces.admin.routes.master_data_profile_settings._refresh_provider_master_data",
        recording_refresh,
    )
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        data={"include_in_no_sales_monitoring": "on"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert calls == ["hydrate"]


def test_machine_profile_post_hydrate_failure_returns_500_after_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_deps: AdminHttpDeps) -> None:
        raise RuntimeError("hydrate failed")

    monkeypatch.setattr(
        "src.interfaces.admin.routes.master_data_profile_settings._refresh_provider_master_data",
        boom,
    )
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    assert deps.master_stores is not None
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        data={},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 500
    machine = deps.master_stores.machines.get(snack_id)
    assert machine is not None
    assert machine.include_in_no_sales_monitoring is False


def test_machine_profile_planogram_grid_not_eighty_rows() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    client = _authed_client(app)
    r = client.get(_snack_workspace_path(snack_id))
    assert r.status_code == 200
    assert b'name="layout_line_number"' not in r.content
    assert b'name="planogram_line_number"' in r.content
    assert b"admin-planogram-grid" in r.content
    assert r.content.count(b'name="planogram_line_number"') == 60


def test_machine_profile_planogram_post_persists_geometry() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"1616": "Чудо"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            slots_per_shelf=12,
            anchors=[(4, 0, "11", "1616", "Чудо")],
            merges=[(4, 0)],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.slots_per_shelf == 12
    assert saved.merges == (SnackPlanogramMerge(4, 0),)
    assert saved.cells == (SnackMachineLayoutCell(11, "1616", 4, 0),)


def test_planogram_post_invalid_line_preserves_form_400() -> None:
    app, deps, _layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"1616": "Чудо"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[
                (0, 0, "5", "1616", "Чудо"),
                (0, 7, "0", "1616", "Чудо"),
            ],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    html = response.text
    assert "layout_error" in html or "invalid_line_number" in html
    assert 'data-slot="7"' in html
    assert "Чудо" in html
    assert response.headers.get("location") is None


def test_planogram_post_sticky_coords_persist_after_reload() -> None:
    import re

    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"1616": "Чудо"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    assert deps.matrix_price_snapshot_store is not None
    _seed_unit_snapshot(
        deps.matrix_price_snapshot_store,
        machine_code=snack_id.value,
        logical_matrix_name=snack_id.value,
    )
    client = _authed_client(app)
    post = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[
                (0, 0, "1", "1616", "Чудо"),
                (0, 7, "8", "1616", "Чудо"),
            ],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert post.status_code in {302, 303}
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.cells == (
        SnackMachineLayoutCell(1, "1616", 0, 0),
        SnackMachineLayoutCell(8, "1616", 0, 7),
    )
    html = client.get(_snack_workspace_path(snack_id)).text
    slot0 = re.search(
        r'<article[^>]*\bdata-shelf="0"[^>]*\bdata-slot="0"[^>]*>.*?</article>',
        html,
        re.DOTALL,
    )
    slot7 = re.search(
        r'<article[^>]*\bdata-shelf="0"[^>]*\bdata-slot="7"[^>]*>.*?</article>',
        html,
        re.DOTALL,
    )
    assert slot0 is not None and "1616" in slot0.group(0)
    assert slot7 is not None and "1616" in slot7.group(0)


def test_machine_profile_planogram_post_invalid_merge_flash() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[(0, 1, "5", "NEW", "X")],
            merges=[(0, 1)],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "invalid_merge_anchor" in r.text
    assert r.headers.get("location") is None


def test_machine_profile_planogram_double_cell_groups_metrics() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    layouts.upsert(
        SnackMachineLayout(
            machine_code=snack_id.value,
            logical_matrix_name=snack_id.value,
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(SnackMachineLayoutCell(11, "NEW"),),
            shelf_count=6,
            slots_per_shelf=10,
            merges=(SnackPlanogramMerge(0, 0),),
        )
    )
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert "planogram-cell--double" in html
    assert "planogram-cell-row-metrics" in html
    assert "planogram-cell-row-price" in html
    assert 'data-span="2"' in html


def test_machine_profile_planogram_legend_documents_load_qty() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert "загрузка" in html.casefold() or "load" in html.casefold()
    assert "ёмк" in html


def test_machine_profile_planogram_post_merge_clears_right() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"1616": "Чудо", "3000": "Уникальный"},
        ),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[
                (0, 0, "11", "1616", "Чудо"),
                (0, 1, "12", "3000", "Уникальный"),
            ],
            merges=[(0, 0)],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.merges == (SnackPlanogramMerge(0, 0),)
    assert saved.cells == (SnackMachineLayoutCell(11, "1616", 0, 0),)


def test_machine_profile_layout_hides_product_code() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    client = _authed_client(app)
    r = client.get(_snack_workspace_path(snack_id))
    assert r.status_code == 200
    assert b'name="planogram_product_code"' in r.content
    assert b'class="planogram-legacy-product-code"' in r.content
    assert b'name="planogram_domain_product_id"' in r.content
    assert b'name="layout_line_number"' not in r.content


def test_machine_planogram_get_offloads_sync_builder_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    client = _authed_client(app)
    response = client.get(_snack_workspace_path(snack_id))
    assert response.status_code == 200
    assert any(getattr(fn, "__name__", "") == "build_machine_planogram_page_sync" for fn in calls)


def test_machine_planogram_page_full_width() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    client = _authed_client(app)
    r = client.get(_snack_workspace_path(snack_id))
    assert r.status_code == 200
    assert b"admin-main--full-width" in r.content
    assert b"admin-planogram-grid" in r.content
    assert b'name="planogram_line_number"' in r.content
    assert b'name="matrix_multiplier"' in r.content
    assert b'name="layout_section"' in r.content
    assert b'id="planogram-shelf-count"' in r.content


def test_machine_profile_coffee_no_layout_editor() -> None:
    app, deps, _layouts, _stock = _build_app()
    coffee_id = seed_coffee(deps)
    client = _authed_client(app)
    r = client.get(f"/admin/machines/{coffee_id.value}")
    assert r.status_code == 200
    assert b'name="planogram_line_number"' not in r.content
    assert b"layout/copy" not in r.content


def test_machine_profile_layout_flag_off_no_editor() -> None:
    app, deps, layouts, _stock = _build_app(layout_master_enabled=False)
    snack_id = seed_snack_with_layout(deps, layouts, line=1, product="NEW")
    client = _authed_client(app)
    r = client.get(f"/admin/machines/{snack_id.value}")
    assert r.status_code == 200
    assert b'name="planogram_line_number"' not in r.content


def test_machine_profile_layout_post_persists_named_rows() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"1616": "Чудо"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(anchors=[(0, 4, "5", "1616", "Чудо")]),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    layout = layouts.get(snack_id.value)
    assert layout is not None
    assert layout.cells == (SnackMachineLayoutCell(5, "1616", 0, 4),)


def test_machine_profile_layout_post_resolves_unique_name() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"3000": "Уникальный"},
        ),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(anchors=[(0, 2, "3", "", "Уникальный")]),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "layout_error" not in (r.headers.get("location") or "")
    layout = layouts.get(snack_id.value)
    assert layout is not None
    assert layout.cells == (SnackMachineLayoutCell(3, "3000", 0, 2),)


def test_machine_profile_layout_post_ambiguous_name_flash() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"1616": "Чудо", "2000": "Чудо"},
        ),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(anchors=[(0, 0, "1", "", "Чудо")]),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "ambiguous_product_name" in r.text
    assert r.headers.get("location") is None


def test_machine_profile_layout_post_duplicate_line_flash() -> None:
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"1616": "Чудо", "3000": "Уникальный"},
        ),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    data = _planogram_post(
        anchors=[
            (0, 0, "7", "1616", "Чудо"),
            (0, 1, "7", "3000", "Уникальный"),
        ],
    )
    r = client.post(
        _layout_path(snack_id),
        data=data,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "duplicate_line_number" in r.text
    assert r.headers.get("location") is None


def test_machine_profile_post_persists_layout() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="OLD")
    code = snack_id.value
    assert deps.matrix_price_snapshot_store is not None
    _seed_unit_snapshot(
        deps.matrix_price_snapshot_store,
        machine_code=code,
        logical_matrix_name=f"M{code}",
    )
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[(0, 0, "12", "NEW", "New Product")],
            auto_sync_enabled=True,
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in {302, 303}
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.cells == (SnackMachineLayoutCell(12, "NEW", 0, 0),)
    assert saved.matrix_multiplier == Decimal("1")
    assert saved.auto_sync_enabled is True


def test_planogram_post_invalid_line_does_not_touch_profile_settings() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    assert deps.master_stores is not None
    before = deps.master_stores.machines.get(snack_id)
    assert before is not None
    assert before.include_in_no_sales_monitoring is True
    client = _authed_client(app)
    response = client.post(
        _layout_path(snack_id),
        data=_planogram_post(anchors=[(0, 0, "0", "NEW", "New Product")]),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "invalid_line_number" in response.text
    after = deps.master_stores.machines.get(snack_id)
    assert after is not None
    assert after.include_in_no_sales_monitoring is True


def test_machine_profile_post_without_layout_section_preserves_layout() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="OLD")
    before = layouts.get(snack_id.value)
    assert before is not None
    client = _authed_client(app)
    r = client.post(
        f"/admin/machines/{snack_id.value}",
        data={
            "include_in_no_sales_monitoring": "on",
            # no layout_section, no layout_line_*
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in {302, 303}
    after = layouts.get(snack_id.value)
    assert after is not None
    assert after.cells == before.cells
    assert after.matrix_multiplier == before.matrix_multiplier
    assert after.auto_sync_enabled == before.auto_sync_enabled


def test_layout_copy_empty_source_returns_400_not_500() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": ""},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "empty_copy_source" in response.text


def test_layout_copy_missing_source_layout_returns_400() -> None:
    app, deps, layouts, _stock = _build_app()
    dest_id = seed_snack_with_layout(deps, layouts, line=1, product="NEW")
    empty_source = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{dest_id.value}/layout/copy",
        data={"source_machine_id": empty_source.value},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "source_layout_missing" in response.text


def test_layout_copy_prg_does_not_call_kit() -> None:
    app, deps, layouts, _stock = _build_app()
    src_id = seed_snack_with_layout(deps, layouts, line=12, product="A")
    dest_id = seed_snack_with_layout(deps, layouts, line=1, product="B")
    dest_before = layouts.get(dest_id.value)
    assert dest_before is not None
    dest_name = dest_before.logical_matrix_name
    client = _authed_client(app)
    r = client.post(
        f"/admin/machines/{dest_id.value}/layout/copy",
        data={"source_machine_id": str(src_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in {302, 303}
    assert f"/admin/snack-planograms/{dest_id.value}" in r.headers.get("location", "")
    dest_after = layouts.get(dest_id.value)
    assert dest_after is not None
    assert dest_after.cells == (SnackMachineLayoutCell(12, "A"),)
    assert dest_after.logical_matrix_name == dest_name
    assert not hasattr(deps, "kit_deployer")


def test_layout_copy_rejects_coffee_http() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="A")
    coffee_id = seed_coffee(deps)
    client = _authed_client(app)
    r = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": str(coffee_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_layout_copy_rejects_coffee_http_shows_flash() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="A")
    coffee_id = seed_coffee(deps)
    client = _authed_client(app)
    r = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": str(coffee_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert b"admin-error" in r.content
    assert b"source_not_snack" in r.content


def test_layout_copy_rejects_self_http() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="A")
    client = _authed_client(app)
    r = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": str(snack_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_layout_page_404_when_flag_off() -> None:
    app, deps, layouts, _stock = _build_app(layout_master_enabled=False)
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    other_id = seed_snack_with_layout(deps, layouts, line=1, product="B")
    client = _authed_client(app)
    r = client.get(_snack_workspace_path(snack_id))
    assert r.status_code == 404
    r_profile = client.get(f"/admin/machines/{snack_id.value}")
    assert r_profile.status_code == 200
    assert b"/layout" not in r_profile.content
    r2 = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": str(other_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r2.status_code == 404


def test_layout_copy_403_without_panel() -> None:
    app, deps, layouts, _stock = _build_app(with_master_panel=False)
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    other_id = seed_snack_with_layout(deps, layouts, line=1, product="B")
    client = _authed_client(app, tg=_TECH_TG)
    r = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": str(other_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_layout_post_allows_zero_capacity_when_sku_catalog_on() -> None:
    from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry

    zero_store = InMemoryMatrixSkuCatalogStore()
    zero_store.upsert(
        MatrixSkuCatalogEntry(
            product_code="ZERO",
            display_name="Zero",
            capacity=0,
            product_multiplier=Decimal("1"),
        )
    )
    app, deps, layouts, _stock = _build_app(
        layout_master_enabled=True,
        with_master_panel=True,
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=zero_store,
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"ZERO": "Zero"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="OLD")
    client = _authed_client(app)
    response = client.post(
        _layout_path(snack_id),
        data=_planogram_post(anchors=[(0, 0, "12", "ZERO", "Zero")]),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {200, 302, 303}
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert any(cell.product_code == "ZERO" for cell in saved.cells)


def test_profile_auto_sync_disabled_without_snapshot() -> None:
    app, deps, layouts, _stock = _build_app()
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    html = _authed_client(app).get(_snack_workspace_path(machine_id)).text
    assert 'name="auto_sync_enabled"' in html
    assert "disabled" in html


def test_profile_save_rejects_auto_sync_without_snapshot() -> None:
    app, deps, layouts, _stock = _build_app()
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    data = _planogram_post()
    data["auto_sync_enabled"] = "on"
    r = client.post(
        _layout_path(machine_id),
        data=data,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "auto_sync_requires_apply" in r.text
    assert r.headers.get("location") is None
    saved = layouts.get(machine_id.value)
    assert saved is None or saved.auto_sync_enabled is False


def test_machine_profile_apply_post_ok() -> None:
    app, deps, layouts, _stock = _build_app()
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    layouts.upsert(
        SnackMachineLayout(
            machine_code=machine_id.value,
            logical_matrix_name=machine_id.value,
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(SnackMachineLayoutCell(1, "SKU1"),),
        )
    )
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{machine_id.value}/layout/apply",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert deps.matrix_price_snapshot_store is not None
    assert deps.matrix_price_snapshot_store.has_unit_snapshot(
        machine_code=machine_id.value,
        logical_matrix_name=machine_id.value,
    )


def test_machine_profile_apply_post_without_margin_flash() -> None:
    app, deps, layouts, _stock = _build_app(with_base_margin=False)
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{machine_id.value}/layout/apply",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = client.get(response.headers["location"] or "")
    assert follow.status_code == 200
    assert "шкал" in follow.text.lower() or "наценк" in follow.text.lower()


def _options_json(html: str) -> str:
    marker = 'id="layout-product-options-json"'
    start = html.index(marker)
    open_tag_end = html.index(">", start) + 1
    close = html.index("</script>", open_tag_end)
    return html[open_tag_end:close].strip()


def test_layout_product_options_exclude_archived_ms_codes() -> None:
    """edge: archived MS codes отсутствуют в JSON autocomplete раскладки."""
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"ARCH": "Old snack", "LIVE": "Live"},
            archived_codes={"ARCH"},
        ),
    )
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="LIVE")
    client = _authed_client(app)
    response = client.get(_snack_workspace_path(snack_id))
    assert response.status_code == 200
    options = json.loads(_options_json(response.text))
    assert "ARCH" not in options
    assert "LIVE" in options


def test_layout_page_warns_legacy_archived_cell() -> None:
    """edge: страница раскладки предупреждает о legacy-ячейке с архивным кодом."""
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"ARCH": "Old snack", "LIVE": "Live"},
            archived_codes={"ARCH"},
        ),
    )
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="ARCH")
    client = _authed_client(app)
    response = client.get(_snack_workspace_path(snack_id))
    assert response.status_code == 200
    assert "архивн" in response.text.lower()


def test_layout_page_shows_legacy_archived_cell_name_without_autocomplete() -> None:
    """edge: имя legacy ARCH гидрируется, но ARCH нет в autocomplete JSON."""
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"ARCH": "Old snack", "LIVE": "Live"},
            archived_codes={"ARCH"},
        ),
    )
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="ARCH")
    client = _authed_client(app)
    response = client.get(_snack_workspace_path(snack_id))
    assert response.status_code == 200
    options = json.loads(_options_json(response.text))
    assert "ARCH" not in options
    assert "Old snack" in response.text
    assert 'name="planogram_product_code"' in response.text
    assert 'value="ARCH"' in response.text


def test_layout_known_includes_archived_snack_codes() -> None:
    """happy: архивный snack MS code остаётся в known-codes раскладки."""
    import asyncio

    from src.interfaces.admin.routes import _layout_known_product_codes

    _app, deps, _layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"ARCH": "Old snack", "LIVE": "Live"},
            archived_codes={"ARCH"},
        ),
    )
    codes = asyncio.run(_layout_known_product_codes(deps))
    assert "ARCH" in codes
    assert "LIVE" in codes


def test_machine_profile_layout_auto_sync_gate_unchanged() -> None:
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="OLD")
    code = snack_id.value
    assert deps.matrix_price_snapshot_store is not None
    _seed_unit_snapshot(
        deps.matrix_price_snapshot_store,
        machine_code=code,
        logical_matrix_name=f"M{code}",
    )
    client = _authed_client(app)
    r = client.post(
        _layout_path(snack_id),
        data=_planogram_post(
            anchors=[(0, 0, "12", "NEW", "New Product")],
            auto_sync_enabled=True,
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code in {302, 303}
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.cells == (SnackMachineLayoutCell(12, "NEW", 0, 0),)
    assert saved.auto_sync_enabled is True


def test_planogram_js_exists() -> None:
    from pathlib import Path

    path = Path("src/interfaces/admin/static/planogram.js")
    text = path.read_text(encoding="utf-8")
    assert "planogram_merge" in text
    assert "duplicate" in text.lower()
    assert "planogram-span-toggle" in text
    assert "machine-planogram-form" in text


def test_layout_page_planogram_form_id_matches_js_init() -> None:
    """happy: /layout form id is what planogram.js looks up."""
    from pathlib import Path

    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert 'id="machine-planogram-form"' in html
    js = Path("src/interfaces/admin/static/planogram.js").read_text(encoding="utf-8")
    assert "machine-planogram-form" in js


def test_layout_page_span_toggle_on_all_anchor_slots() -> None:
    """happy: every anchor slot has span toggle; odd slots merge left."""
    import re

    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert "Двойная" not in html
    assert "planogram-span-toggle" in html
    assert 'data-merge-direction="left"' in html
    assert 'data-merge-direction="right"' in html
    match = re.search(r'<article[^>]*\bdata-slot="9"[^>]*>', html)
    assert match is not None
    odd_cell = html[match.start() :].split("</article>", 1)[0]
    assert "planogram-span-toggle" in odd_cell
    assert 'data-merge-direction="left"' in odd_cell


def test_layout_page_no_purchase_price_chip() -> None:
    """happy: purchase chip removed from cell card."""
    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert "chip-purchase" not in html
    assert "расч · тек" in html
    assert "зак · расч" not in html


def test_layout_page_product_name_has_suggestions_list() -> None:
    """happy: domain-product typeahead picker replaces free-text name field."""
    app, deps, layouts, _stock = _build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="NEW")
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert 'name="planogram_domain_product_id"' in html
    assert "planogram-product-picker" in html
    assert "planogram-product-search" in html
    assert "planogram-product-list-btn" not in html
    assert 'name="planogram_product_name"' not in html


def test_layout_page_planogram_static_assets_have_cache_bust_query() -> None:
    """happy: planogram.js and planogram.css served with ?v= mtime query."""
    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    html = _authed_client(app).get(_snack_workspace_path(snack_id)).text
    assert "planogram.js?v=" in html
    assert "planogram.css?v=" in html
    assert "/admin/static/planogram.js?v=" in html
    assert "/admin/static/planogram.css?v=" in html


def test_layout_copy_error_page_has_versioned_planogram_static() -> None:
    """edge: copy error re-render includes cache-busted static like GET /layout."""
    app, deps, layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    resp = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": ""},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "planogram.js?v=" in resp.text
    assert "planogram.css?v=" in resp.text


def test_planogram_css_cell_overflow_and_control_radius() -> None:
    """edge/static: overflow visible on .planogram-cell; chip rows clip; gray toggle."""
    import re
    from pathlib import Path

    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    cell_rules = re.findall(r"\.planogram-cell\s*\{[^}]+\}", css)
    assert cell_rules and any(
        "overflow: visible" in rule or "overflow:visible" in rule for rule in cell_rules
    )
    row_rules = re.findall(r"\.planogram-cell-row\s*\{[^}]+\}", css)
    assert row_rules and any(
        "overflow: hidden" in rule or "overflow:hidden" in rule for rule in row_rules
    )
    assert "--control-h" in css
    assert "--radius" in css
    assert ".planogram-span-toggle" in css
    assert "--chip-group-w" in css
    assert "#e5e7eb" in css
    stock_w = re.search(r"\.chip-group-stock\s*\{[^}]*width:\s*var\(--chip-group-w\)", css)
    price_w = re.search(r"\.chip-group-price\s*\{[^}]*width:\s*var\(--chip-group-w\)", css)
    assert stock_w and price_w
    chip_rules = re.findall(r"\.chip\s*\{[^}]+\}", css)
    assert chip_rules and all("999px" not in rule for rule in chip_rules)
    group_rules = re.findall(r"\.chip-group\s*\{[^}]+\}", css)
    assert group_rules and all("999px" not in rule for rule in group_rules)


def test_planogram_css_name_suggestions_wide_panel() -> None:
    """happy/static: suggestions panel breaks out of narrow grid column."""
    import re
    from pathlib import Path

    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    sugg_rules = re.findall(r"\.planogram-name-suggestions\s*\{[^}]+\}", css, re.DOTALL)
    assert sugg_rules, "missing .planogram-name-suggestions rule"
    rule = sugg_rules[0]
    assert "right: auto" in rule or "right:auto" in rule
    assert "min-width: 20rem" in rule or "min-width:20rem" in rule
    assert "width: max-content" in rule or "width:max-content" in rule
    assert "max-width: min(28rem" in rule or "max-width:min(28rem" in rule
    assert "overflow-x: hidden" in rule or "overflow-x:hidden" in rule
    assert "overflow-y: auto" in rule or "overflow-y:auto" in rule
    assert "z-index: 30" in rule or "z-index:30" in rule

    li_rules = re.findall(r"\.planogram-name-suggestions li\s*\{[^}]+\}", css, re.DOTALL)
    assert li_rules, "missing .planogram-name-suggestions li rule"
    li_rule = li_rules[0]
    assert "white-space: nowrap" in li_rule or "white-space:nowrap" in li_rule
    assert "text-overflow: ellipsis" in li_rule or "text-overflow:ellipsis" in li_rule
    assert "overflow: hidden" in li_rule or "overflow:hidden" in li_rule


def test_planogram_js_name_suggestions_viewport_flip_contract() -> None:
    """legacy autocomplete helpers may remain; picker owns product selection."""
    from pathlib import Path

    js = Path("src/interfaces/admin/static/planogram.js").read_text(encoding="utf-8")
    assert "function buildPickerMarkup" in js
    assert "planogram_domain_product_id" in js
    assert "planogram-product-picker" in js


def test_planogram_js_init_and_span_toggle_contract() -> None:
    """happy: JS binds planogram form, span toggle, domain-product picker."""
    from pathlib import Path

    js = Path("src/interfaces/admin/static/planogram.js").read_text(encoding="utf-8")
    assert "machine-planogram-form" in js
    assert "planogram-span-toggle" in js
    assert "data-merge-direction" in js
    assert "chip-purchase" not in js
    assert "planogram_merge_shelf" in js
    assert "Двойная" not in js
    assert "planogram-merge-checkbox" not in js
    assert "planogram_domain_product_id" in js
    assert "buildPickerMarkup" in js


def _kefir_store() -> MemoryDomainProductStore:
    store = MemoryDomainProductStore()
    create_domain_product("Кефир", store=store, lookup=FakeCatalogLookup(()))
    return store


def _kefir_id(deps: AdminHttpDeps) -> str:
    assert deps.domain_product_store is not None
    visible = deps.domain_product_store.list_visible()
    assert len(visible) >= 1
    return visible[0].domain_product_id


def _kefir_and_linked_store() -> MemoryDomainProductStore:
    store = MemoryDomainProductStore()
    create_domain_product("Кефир", store=store, lookup=FakeCatalogLookup(()))
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    linked = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(linked.domain_product_id, "2311", store=store, lookup=lookup)
    return store


def _seed_snack_cell(
    deps: AdminHttpDeps,
    layouts: InMemorySnackMachineLayoutStore,
    *,
    domain_product_id: str | None,
    product_code: str | None,
    line: int = 1,
) -> MachineId:
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    code = machine_id.value
    layouts.upsert(
        SnackMachineLayout(
            machine_code=code,
            logical_matrix_name=f"M{code}",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(
                SnackMachineLayoutCell(
                    line,
                    product_code,
                    0,
                    0,
                    domain_product_id=domain_product_id,
                ),
            ),
        )
    )
    return machine_id


def _seed_two_cells(
    deps: AdminHttpDeps,
    layouts: InMemorySnackMachineLayoutStore,
    store: DomainProductStore,
) -> MachineId:
    visible = store.list_visible()
    by_name = {product.name: product for product in visible}
    kefir = by_name["Кефир"]
    salad = by_name["Салат"]
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    code = machine_id.value
    layouts.upsert(
        SnackMachineLayout(
            machine_code=code,
            logical_matrix_name=f"M{code}",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(
                SnackMachineLayoutCell(
                    1,
                    None,
                    0,
                    0,
                    domain_product_id=kefir.domain_product_id,
                ),
                SnackMachineLayoutCell(
                    2,
                    None,
                    0,
                    1,
                    domain_product_id=salad.domain_product_id,
                ),
            ),
        )
    )
    return machine_id


def test_snack_planogram_picker_links_unlinked_product() -> None:
    app, deps, layouts, _stock = _build_app(domain_product_store=_kefir_store())
    machine_id = _seed_snack_cell(
        deps,
        layouts,
        domain_product_id=_kefir_id(deps),
        product_code=None,
    )
    response = _authed_client(app).get(_snack_workspace_path(machine_id))
    assert 'target="_blank"' in response.text
    assert "planogram-product-unlinked" in response.text
    assert "Кефир" in response.text
    assert 'class="planogram-product-name"' not in response.text


def test_snack_planogram_legacy_code_has_no_unlinked_class() -> None:
    app, deps, layouts, _stock = _build_app(domain_product_store=_kefir_store())
    machine_id = _seed_snack_cell(
        deps,
        layouts,
        domain_product_id=None,
        product_code="2311",
    )
    response = _authed_client(app).get(_snack_workspace_path(machine_id))
    assert "planogram-product-unlinked" not in response.text
    assert "/admin/domain-products/" not in response.text


def test_snack_planogram_legacy_code_shows_matching_product() -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    product = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    app, deps, layouts, _stock = _build_app(domain_product_store=store)
    machine_id = _seed_snack_cell(
        deps,
        layouts,
        domain_product_id=None,
        product_code="2311",
    )
    response = _authed_client(app).get(_snack_workspace_path(machine_id))
    assert response.status_code == 200
    assert f'href="/admin/domain-products/{product.domain_product_id}"' in response.text
    assert "Салат" in response.text


def test_snack_apply_nothing_to_send_uses_planogram_phrase() -> None:
    store = _kefir_store()
    app, deps, layouts, _stock = _build_app(domain_product_store=store)
    machine_id = _seed_snack_cell(
        deps,
        layouts,
        domain_product_id=_kefir_id(deps),
        product_code=None,
    )
    response = _authed_client(app).post(
        f"{_layout_path(machine_id)}/apply",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "В Kit ничего не отправлено" in unquote(response.headers["location"])


def test_snack_apply_partial_lists_skipped_name() -> None:
    store = _kefir_and_linked_store()
    app, deps, layouts, _stock = _build_app(domain_product_store=store)
    machine_id = _seed_two_cells(deps, layouts, store)
    response = _authed_client(app).post(
        f"{_layout_path(machine_id)}/apply",
        headers={"Origin": "http://testserver"},
        follow_redirects=True,
    )
    assert "Не отправлено, нет связи с МойСкладом: Кефир" in response.text


def test_snack_planogram_save_error_keeps_selected_product_name() -> None:
    store = _kefir_store()
    app, deps, _layouts, _stock = _build_app(domain_product_store=store)
    kefir_id = _kefir_id(deps)
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    response = _authed_client(app).post(
        _layout_path(snack_id),
        data={
            "layout_section": "1",
            "matrix_multiplier": "1",
            "planogram_shelf_count": "6",
            "planogram_slots_per_shelf": "10",
            "planogram_shelf_index": ["0"],
            "planogram_slot_index": ["0"],
            "planogram_line_number": ["0"],
            "planogram_product_code": [""],
            "planogram_domain_product_id": [kefir_id],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Кефир" in response.text
    assert "Товар не найден" not in response.text
    assert kefir_id in response.text


def test_snack_planogram_linked_domain_product_shows_capacity() -> None:
    from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry

    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    product = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    sku_store = InMemoryMatrixSkuCatalogStore()
    sku_store.upsert(
        MatrixSkuCatalogEntry(
            product_code="2311",
            display_name="Салат",
            capacity=12,
            product_multiplier=Decimal("1"),
        )
    )
    app, deps, layouts, _stock = _build_app(
        domain_product_store=store,
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=sku_store,
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({"2311": "Салат"}),
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    machine_id = _seed_snack_cell(
        deps,
        layouts,
        domain_product_id=product.domain_product_id,
        product_code=None,
    )
    response = _authed_client(app).get(_snack_workspace_path(machine_id))
    assert response.status_code == 200
    assert 'aria-label="ёмк">12</span>' in response.text
    assert "Салат" in response.text
    assert "planogram-product-unlinked" not in response.text


def test_planogram_js_keeps_capacity_when_domain_id_set() -> None:
    from pathlib import Path

    text = Path("src/interfaces/admin/static/planogram.js").read_text(encoding="utf-8")
    assert "syncCapacityFromCode" in text
    assert "domainIdField" in text
    assert "data-unlinked" in text
    start = text.index("function syncCapacityFromCode")
    chunk = text[start : start + 700]
    assert "domainIdField(cell)" in chunk
    assert "data-unlinked" in chunk


def test_planogram_get_without_assortment_reader_degrades_200() -> None:
    # happy / ADR-0083: reader None → 200 without raising configured-error
    from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry

    sku_store = InMemoryMatrixSkuCatalogStore()
    sku_store.upsert(
        MatrixSkuCatalogEntry(
            product_code="1616",
            display_name="Чудо",
            capacity=5,
            product_multiplier=Decimal("1"),
        )
    )
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=sku_store,
        snack_sku_assortment_reader=None,
    )
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="1616")
    r = _authed_client(app).get(_snack_workspace_path(snack_id))
    assert r.status_code == 200
    assert b"admin-planogram-grid" in r.content


def test_planogram_post_without_assortment_reader_uses_enrolled_store() -> None:
    # happy / ADR-0083: no live Remap → persist via enrolled catalog, not 502
    from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry

    sku_store = InMemoryMatrixSkuCatalogStore()
    sku_store.upsert(
        MatrixSkuCatalogEntry(
            product_code="1616",
            display_name="Чудо",
            capacity=5,
            product_multiplier=Decimal("1"),
        )
    )
    app, deps, layouts, _stock = _build_app(
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=sku_store,
        snack_sku_assortment_reader=None,
    )
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    r = _authed_client(app).post(
        _layout_path(snack_id),
        data=_planogram_post(
            slots_per_shelf=12,
            anchors=[(4, 0, "11", "1616", "Чудо")],
            merges=[(4, 0)],
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = layouts.get(snack_id.value)
    assert saved is not None
    assert saved.cells == (SnackMachineLayoutCell(11, "1616", 4, 0),)
