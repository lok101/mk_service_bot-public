from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores, MachineKind, MachineStatus
from src.application.master_data.models import MasterMachine
from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.micromarket_loading.ports import (
    MicromarketAssemblyOrderStore,
    MicromarketSupplyOrderStore,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.micromarket_loading.supply_order_forecast import (
    AlwaysUnavailableSupplyOrderForecast,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.application.product_identity import DomainProduct
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.assembly_order import (
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
)
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketAssemblyOrderStore,
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketSupplyOrderStore,
    InMemoryMicromarketWarehouseStockSnapshotStore,
)
from src.interfaces.admin.deps import AdminHttpDeps, KitProductGroupsLoad
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.routes.micromarket_loading import _decimal_at

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


def _seed_product_catalog(provider: ReferenceDataProvider) -> None:
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["2311", "Салат Цезарь", "product"],
            ["2312", "Вода 0.5", "product"],
        ],
    )


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _FakeMoveGateway:
    def __init__(self, *, warehouse: dict[str, Decimal] | None = None) -> None:
        self._warehouse = warehouse or {}
        self.create_calls: list[tuple[str, str, Sequence[tuple[str, Decimal]]]] = []

    def warehouse_qty(self, product_code: str) -> Decimal:
        return self._warehouse.get(product_code, Decimal("0"))

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return {code: self._warehouse.get(code, Decimal("0")) for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        self.create_calls.append((order_id, machine_code, positions))
        return f"move-{order_id}"

    def delete_move(self, *, move_id: str) -> None:
        return None

    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        del order_id, now
        return False


_READY_FOLDER = "7203a901-b1b2-11f1-0a80-115a00344501"
_SNACKS_FOLDER = "4c2738f1-f43a-11ef-0a80-1a2b002150a4"


class FakeSupplyOrderCategoryFacts:
    def fetch_by_catalog_codes(self, catalog_codes):
        from src.application.micromarket_loading.supply_order_category import (
            SupplyOrderCategoryProductFacts,
        )

        return tuple(
            SupplyOrderCategoryProductFacts(
                catalog_code=code,
                folder_ancestor_ids=(_READY_FOLDER,),
                shelf_life_days=7,
            )
            for code in catalog_codes
        )


def _build_app(
    *,
    machine_kind: MachineKind = MachineKind.MICRO_MARKET,
    machine_id: str = "701",
    seed_preview: bool = False,
    seed_shelves: bool = False,
    kit_groups: tuple[tuple[int, str], ...] = (),
    cycle_store: MicromarketLoadingCycleStore | None = None,
    supply_order_store: MicromarketSupplyOrderStore | None = None,
    assembly_order_store: MicromarketAssemblyOrderStore | None = None,
    execute_enabled: bool = False,
    move_gateway: MicromarketMoveGateway | None = None,
    warehouse_stock_snapshot: MicromarketWarehouseStockSnapshotPort | None = None,
    warehouse_stock_cold_wait_seconds: int = 15,
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
    _seed_product_catalog(provider)
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
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    if seed_shelves:
        planogram_store.upsert(
            MicromarketPlanogram(
                machine_code=machine_id,
                lines=(
                    MicromarketPlanogramLine(
                        "2311",
                        5,
                        Decimal("189.00"),
                        True,
                        0,
                        kit_group_id=10,
                    ),
                    MicromarketPlanogramLine(
                        "2312",
                        3,
                        Decimal("50.00"),
                        True,
                        1,
                        kit_group_id=20,
                    ),
                ),
                updated_at=_FROZEN_NOW,
                shelves=(
                    MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                    MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
                ),
            ),
        )
        stock = MicromarketDeviceStock(machine_code=machine_id)
        stock.apply_inventory(
            as_of=_FROZEN_NOW,
            quantities={"2311": Decimal("2"), "2312": Decimal("1")},
            inventory_id="inv-shelves-1",
        )
        stock_store.save(stock)
    elif seed_preview:
        planogram_store.upsert(
            MicromarketPlanogram(
                machine_code=machine_id,
                lines=(
                    MicromarketPlanogramLine(
                        "2311",
                        5,
                        Decimal("189.00"),
                        True,
                        0,
                    ),
                ),
                updated_at=_FROZEN_NOW,
            ),
        )
        stock = MicromarketDeviceStock(machine_code=machine_id)
        stock.apply_inventory(
            as_of=_FROZEN_NOW,
            quantities={"2311": Decimal("2")},
            inventory_id="inv-preview-1",
        )
        stock_store.save(stock)
    domain_products = MemoryDomainProductStore()
    domain_products.insert(
        DomainProduct(
            domain_product_id="dp-2311",
            number="2311",
            name="Салат Цезарь",
            catalog_code="2311",
            hidden=False,
        ),
    )
    domain_products.insert(
        DomainProduct(
            domain_product_id="dp-2312",
            number="2312",
            name="Вода 0.5",
            catalog_code="2312",
            hidden=False,
        ),
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
        master_stores=master_stores,
        users_enabled=False,
        micromarket_planogram_store=planogram_store,
        micromarket_stock_store=stock_store,
        micromarket_loading_cycle_store=cycle_store,
        micromarket_assembly_order_store=(
            assembly_order_store
            if assembly_order_store is not None
            else InMemoryMicromarketAssemblyOrderStore()
        ),
        micromarket_supply_order_store=supply_order_store,
        supply_order_category_facts=FakeSupplyOrderCategoryFacts(),
        supply_order_demand_forecast=AlwaysUnavailableSupplyOrderForecast(),
        supply_order_snacks_folder_id=_SNACKS_FOLDER,
        supply_order_ready_meals_folder_id=_READY_FOLDER,
        supply_order_shelf_life_days_threshold=7,
        micromarket_loading_execute_enabled=execute_enabled,
        micromarket_loading_move_gateway=move_gateway,
        micromarket_warehouse_stock_snapshot=warehouse_stock_snapshot,
        micromarket_warehouse_stock_cold_wait_seconds=warehouse_stock_cold_wait_seconds,
        domain_product_store=domain_products,
        load_kit_product_groups=lambda: KitProductGroupsLoad(error="", groups=kit_groups),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def _build_app_with_micromarket_loading_preview(
    *,
    cycle_store: MicromarketLoadingCycleStore | None = None,
    supply_order_store: MicromarketSupplyOrderStore | None = None,
    execute_enabled: bool = False,
    move_gateway: MicromarketMoveGateway | None = None,
    warehouse_stock_snapshot: MicromarketWarehouseStockSnapshotPort | None = None,
    warehouse_stock_cold_wait_seconds: int = 15,
) -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(
        machine_kind=MachineKind.MICRO_MARKET,
        machine_id="701",
        seed_preview=True,
        cycle_store=cycle_store,
        supply_order_store=supply_order_store,
        execute_enabled=execute_enabled,
        move_gateway=move_gateway,
        warehouse_stock_snapshot=warehouse_stock_snapshot,
        warehouse_stock_cold_wait_seconds=warehouse_stock_cold_wait_seconds,
    )


def _build_app_with_micro_machine() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(machine_kind=MachineKind.MICRO_MARKET, machine_id="701")


def _build_app_with_snack_machine() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(machine_kind=MachineKind.SNACK, machine_id="501")


def test_loading_preview_get_renders_columns() -> None:
    app, _deps = _build_app_with_micromarket_loading_preview()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    body = response.content.lower()
    assert b"2311" in response.content or b"stock" in body


def test_assembly_page_shows_create_order() -> None:
    app, _deps = _build_app_with_micromarket_loading_preview()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    text = _assembly_panel_html(response.text)
    assert "Сохранить черновик" not in text
    assert "Создать ордер сборки" in text
    assert "/micromarket-loading/draft" not in text
    assert "Запустить загрузку" not in text
    assert "В загрузку" not in text


class _WarehouseFailGateway(_FakeMoveGateway):
    def warehouse_qty(self, product_code: str) -> Decimal:
        del product_code
        raise RuntimeError("warehouse unread")

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        del product_codes
        raise RuntimeError("warehouse unread")


def test_fridge_workspace_survives_warehouse_read_failure_on_loading_tab() -> None:
    app, _deps = _build_app_with_micromarket_loading_preview(
        execute_enabled=True,
        move_gateway=_WarehouseFailGateway(warehouse={"2311": Decimal("5")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    assert b"2311" in response.content


class _CountingMoveGateway(_FakeMoveGateway):
    warehouse_calls = 0

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        type(self).warehouse_calls += 1
        return super().warehouse_qty_by_codes(product_codes)


def test_planogram_tab_skips_moysklad_warehouse_preview() -> None:
    _CountingMoveGateway.warehouse_calls = 0
    app, _deps = _build_app_with_micromarket_loading_preview(
        execute_enabled=True,
        move_gateway=_CountingMoveGateway(warehouse={"2311": Decimal("5")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert _CountingMoveGateway.warehouse_calls == 0


def test_profile_has_no_loading_link_for_micro_market() -> None:
    app, _deps = _build_app_with_micro_machine()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines/701")
    assert response.status_code == 200
    assert b"/machines/701/micromarket-loading" not in response.content


def test_loading_wrong_kind_404() -> None:
    app, _deps = _build_app_with_snack_machine()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines/501/micromarket-loading")
    assert response.status_code == 404


def test_loading_launch_when_disabled_keeps_shelf() -> None:
    cycle_store = _MemoryCycleStore()
    app, deps = _build_app_with_micromarket_loading_preview(
        cycle_store=cycle_store,
        execute_enabled=False,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    assert deps.micromarket_stock_store is not None
    before = deps.micromarket_stock_store.load("701")
    before_qty = before.qty("2311") if before is not None else None
    response = client.post(
        "/admin/machines/701/micromarket-loading",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "загрузка выключена" in response.text.casefold()
    after = deps.micromarket_stock_store.load("701")
    after_qty = after.qty("2311") if after is not None else None
    assert after_qty == before_qty


def test_loading_rollback_button_only_when_open() -> None:
    app, _deps = _build_app_with_micromarket_loading_preview()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert "Откатить" not in response.text
    assert "откатить" not in response.text.casefold()

    cycle_store = _MemoryCycleStore()
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
        ),
    )
    cycle.open_order(
        order_id="ord-1",
        move_id="mv-1",
        lines=cycle.lines,
        opened_at=_FROZEN_NOW,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )
    cycle.pull_events()
    cycle_store.save(cycle)
    assert cycle.status is OrderStatus.OPEN

    app2, _deps2 = _build_app_with_micromarket_loading_preview(cycle_store=cycle_store)
    client2 = TestClient(app2)
    client2.post("/admin/auth/telegram", data=_signed_widget_fields())
    response2 = client2.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response2.status_code == 200
    assert "Откатить" not in response2.text
    loading_tab = client2.get("/admin/micromarket-planograms/701?tab=loading")
    assert loading_tab.status_code == 200
    assert "Откатить" in loading_tab.text
    assert 'id="micromarket-loading-rollback-form"' in loading_tab.text


def test_planogram_list_links_name_and_exports() -> None:
    supply_store = InMemoryMicromarketSupplyOrderStore()
    app, _deps = _build_app_with_micromarket_loading_preview(supply_order_store=supply_store)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms")
    assert response.status_code == 200
    assert "/admin/micromarket-planograms/701" in response.text

    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": "2026-10-10T15:00"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert "tab=orders" in create.headers["location"]
    assert len(supply_store.list_newest()) == 1
    order_id = supply_store.list_newest()[0].order_id
    assert f"download={order_id}" in create.headers["location"]
    download = client.get(f"/admin/micromarket-planograms/orders/{order_id}/download")
    assert download.status_code == 200
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_loading_post_wrong_kind_404() -> None:
    app, _deps = _build_app_with_snack_machine()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/501/micromarket-loading",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 404


def test_loading_launch_persists_submitted_qty_when_disabled() -> None:
    cycle_store = _MemoryCycleStore()
    app, deps = _build_app_with_micromarket_loading_preview(
        cycle_store=cycle_store,
        execute_enabled=False,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    assert deps.micromarket_stock_store is not None
    before = deps.micromarket_stock_store.load("701")
    before_qty = before.qty("2311") if before is not None else None
    response = client.post(
        "/admin/machines/701/micromarket-loading",
        data={
            "product_code": "2311",
            "target_qty": "5",
            "stock_qty": "2",
            "need_qty": "7",
            "launch_qty": "4",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "загрузка выключена" in response.text.casefold()
    after = deps.micromarket_stock_store.load("701")
    after_qty = after.qty("2311") if after is not None else None
    assert after_qty == before_qty
    saved = cycle_store.load("701")
    assert saved is not None
    # need_qty from form ignored for SoT; service field = live gap (5-2)
    assert saved.lines[0].need_qty == Decimal("3")
    assert saved.lines[0].launch_qty == Decimal("4")


def test_loading_launch_rejected_shows_reason() -> None:
    cycle_store = _MemoryCycleStore()
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=5,
                stock_qty=Decimal("2"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("0"),
            ),
        ),
    )
    cycle.pull_events()
    cycle_store.save(cycle)
    gateway = _FakeMoveGateway(warehouse={"2311": Decimal("10")})
    app, _deps = _build_app_with_micromarket_loading_preview(
        cycle_store=cycle_store,
        execute_enabled=True,
        move_gateway=gateway,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-loading",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "all_launch_qty_zero" in response.text


def _seed_open_order(cycle_store: _MemoryCycleStore) -> DraftLine:
    original = DraftLine(
        product_code="2311",
        target_qty=5,
        stock_qty=Decimal("2"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft((original,))
    cycle.open_order(
        order_id="ord-open-1",
        move_id="mv-open-1",
        lines=cycle.lines,
        opened_at=_FROZEN_NOW,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )
    cycle.pull_events()
    cycle_store.save(cycle)
    assert cycle.status is OrderStatus.OPEN
    return original


def test_loading_launch_does_not_overwrite_open_order_lines() -> None:
    cycle_store = _MemoryCycleStore()
    original = _seed_open_order(cycle_store)
    app, _deps = _build_app_with_micromarket_loading_preview(
        cycle_store=cycle_store,
        execute_enabled=False,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-loading",
        data={
            "product_code": "2311",
            "target_qty": "5",
            "stock_qty": "2",
            "need_qty": "9",
            "launch_qty": "8",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    saved = cycle_store.load("701")
    assert saved is not None
    assert saved.status is OrderStatus.OPEN
    assert saved.lines == (original,)
    assert saved.lines[0].need_qty == Decimal("3")
    assert saved.lines[0].launch_qty == Decimal("2")


def test_loading_draft_decimal_accepts_comma() -> None:
    # happy
    assert _decimal_at(["1,5"], 0, default=Decimal("0")) == Decimal("1.5")


def test_loading_draft_decimal_percent_follows_canon() -> None:
    # happy: канон снимает хвостовой %
    assert _decimal_at(["12%"], 0, default=Decimal("0")) == Decimal("12")


def test_loading_draft_decimal_invalid_keeps_default() -> None:
    # edge
    assert _decimal_at([""], 0, default=Decimal("0")) == Decimal("0")
    assert _decimal_at(["abc"], 0, default=Decimal("0")) == Decimal("0")
    assert _decimal_at([], 0, default=Decimal("3")) == Decimal("3")


def test_loading_preview_and_launch_pass_domain_product_store() -> None:
    from pathlib import Path

    routes = Path("src/interfaces/admin/routes")
    preview = (routes / "micromarket_loading_assembly_tab.py").read_text(encoding="utf-8")
    preview_start = preview.index("GetMicromarketLoadingPreview(")
    preview_chunk = preview[preview_start : preview_start + 280]
    assert "products=deps.domain_product_store" in preview_chunk
    for name in (
        "micromarket_loading_cycle.py",
        "micromarket_loading_assembly.py",
    ):
        text = (routes / name).read_text(encoding="utf-8")
        launch_start = text.index("LaunchMicromarketLoading(")
        launch_chunk = text[launch_start : launch_start + 800]
        assert "products=deps.domain_product_store" in launch_chunk


def test_loading_need_readonly_and_launch_uses_stepper() -> None:
    # happy: need read-only; «В сборку» — степпер; script подключён
    app, _deps = _build_app_with_micromarket_loading_preview()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "admin_quantity_stepper.js" in html
    assert 'name="launch_qty"' in html
    assert 'name="assembly_qty"' in html
    assembly_idx = html.index('class="admin-qty-input"')
    assembly_window = html[max(0, assembly_idx - 400) : assembly_idx + 200]
    assert "admin-qty-stepper" in assembly_window
    assert 'name="assembly_qty"' in assembly_window
    assert 'data-dir="-1"' in assembly_window
    assert 'max="9999"' in assembly_window or "data-max=" in assembly_window
    assert 'max="50"' not in assembly_window
    assert "admin-need-from-live" in html
    need_idx = html.index("admin-need-from-live")
    need_window = html[need_idx : need_idx + 200]
    assert "admin-qty-stepper" not in need_window


def test_loading_preview_uses_last_supply_order_need() -> None:
    supply_store = InMemoryMicromarketSupplyOrderStore()
    supply_store.save(
        MicromarketSupplyOrder(
            order_id="so-last",
            created_at=_FROZEN_NOW,
            expected_arrival_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            machines=(
                MicromarketSupplyOrderMachine(
                    machine_id="701",
                    lines=(
                        MicromarketSupplyOrderLine(
                            product_code="2311",
                            need_qty=Decimal("9"),
                            category=2,
                            name="Салат",
                        ),
                    ),
                ),
            ),
        ),
    )
    app, _deps = _build_app_with_micromarket_loading_preview(supply_order_store=supply_store)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    assert "admin-need-from-live" not in response.text
    assert ">9<" in response.text or 'value="9"' in response.text


def _assembly_panel_html(page_html: str) -> str:
    marker = 'class="admin-workspace-panel" data-tab="assembly"'
    start = page_html.index(marker)
    return page_html[start:]


def _loading_orders_panel_html(page_html: str) -> str:
    marker = 'class="admin-workspace-panel" data-tab="loading"'
    start = page_html.index(marker)
    return page_html[start:]


def test_loading_tab_uses_warehouse_snapshot_qty_without_live_bystore() -> None:
    """happy: GET loading reads snapshot qty; gateway warehouse batch not called."""
    snapshot = InMemoryMicromarketWarehouseStockSnapshotStore()
    snapshot.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("11"), "2312": Decimal("8")},
        ),
    )
    _CountingMoveGateway.warehouse_calls = 0
    app, _deps = _build_app(
        seed_shelves=True,
        kit_groups=((10, "Полка A"), (20, "Полка B")),
        execute_enabled=True,
        move_gateway=_CountingMoveGateway(warehouse={"2311": Decimal("99"), "2312": Decimal("99")}),
        warehouse_stock_snapshot=snapshot,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert ">11<" in html
    assert ">8<" in html
    assert _CountingMoveGateway.warehouse_calls == 0


def test_loading_tab_cold_wait_timeout_degrades_warehouse_column(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """edge: empty snapshot + cold_wait=0 → degrade (—), no live bystore."""
    empty = InMemoryMicromarketWarehouseStockSnapshotStore()
    _CountingMoveGateway.warehouse_calls = 0
    app, _deps = _build_app(
        seed_preview=True,
        execute_enabled=True,
        move_gateway=_CountingMoveGateway(warehouse={"2311": Decimal("99")}),
        warehouse_stock_snapshot=empty,
        warehouse_stock_cold_wait_seconds=0,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    with caplog.at_level("WARNING"):
        response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "На складе" in html
    assert "—" in html
    assert ">99<" not in html
    assert _CountingMoveGateway.warehouse_calls == 0
    assert any(
        "micromarket_loading_preview_warehouse_snapshot_cold_timeout" in record.message
        for record in caplog.records
    )


def test_loading_tab_groups_by_shelf_and_shows_warehouse_column() -> None:
    # happy: две полки, колонка «На складе», подписи На полке / Цель / Нужно
    app, _deps = _build_app(
        seed_shelves=True,
        kit_groups=((10, "Полка A"), (20, "Полка B")),
        execute_enabled=True,
        move_gateway=_FakeMoveGateway(
            warehouse={"2311": Decimal("7.0"), "2312": Decimal("4.0")},
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "На полке" in html
    assert "Цель" in html
    assert "Нужно" in html
    assert "На складе" in html
    assert "Полка A" in html
    assert "Полка B" in html
    assert html.index("Полка A") < html.index("2311")
    assert html.index("Полка B") < html.index("2312")
    assert html.index("Полка A") < html.index("Полка B")
    assert ">7<" in html
    assert ">4<" in html
    assert ">7.0<" not in html
    assert ">4.0<" not in html


def test_loading_tab_ungrouped_line_uses_bez_polki_section() -> None:
    # edge: line без kit_group → секция «Без полки»
    app, deps = _build_app(
        seed_preview=True,
        kit_groups=((10, "Полка A"),),
        execute_enabled=True,
        move_gateway=_FakeMoveGateway(warehouse={"2311": Decimal("3"), "2312": Decimal("1")}),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    "2311",
                    5,
                    Decimal("189.00"),
                    True,
                    0,
                    kit_group_id=10,
                ),
                MicromarketPlanogramLine(
                    "2312",
                    2,
                    Decimal("50.00"),
                    True,
                    1,
                    kit_group_id=None,
                ),
            ),
            updated_at=_FROZEN_NOW,
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "Полка A" in html
    assert "Без полки" in html
    assert html.index("Полка A") < html.index("Без полки")


def test_loading_tab_default_launch_is_min_need_and_warehouse() -> None:
    # happy: без draft launch = min(need, warehouse); склад без .0; max степпера >50
    app, _deps = _build_app_with_micromarket_loading_preview(
        execute_enabled=True,
        move_gateway=_FakeMoveGateway(warehouse={"2311": Decimal("10")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert 'name="launch_qty"' in html
    launch_idx = html.index('name="launch_qty"')
    window = html[max(0, launch_idx - 200) : launch_idx + 250]
    assert 'value="3"' in window
    assert ">10<" in html
    assert ">10.0<" not in html
    assert 'max="50"' not in window


def test_loading_tab_closed_cycle_zeros_recompute_launch() -> None:
    # edge: closed с launch=0 не держит нули — пересчёт initial
    cycle_store = _MemoryCycleStore()
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=5,
                stock_qty=Decimal("2"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("0"),
            ),
        ),
    )
    cycle.open_order(
        order_id="ord-closed-1",
        move_id="mv-closed-1",
        lines=cycle.lines,
        opened_at=_FROZEN_NOW,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )
    cycle.close_without_recount(at=_FROZEN_NOW)
    cycle.pull_events()
    cycle_store.save(cycle)
    assert cycle.status is OrderStatus.CLOSED

    app, _deps = _build_app_with_micromarket_loading_preview(
        cycle_store=cycle_store,
        execute_enabled=True,
        move_gateway=_FakeMoveGateway(warehouse={"2311": Decimal("10")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    launch_idx = html.index('name="launch_qty"')
    window = html[max(0, launch_idx - 200) : launch_idx + 250]
    assert 'value="3"' in window


def test_loading_tab_empty_snapshot_degrades_warehouse_not_zeros() -> None:
    """edge: снимок без кодов планограммы → «—» и launch от need, не нули склада."""
    empty_codes = InMemoryMicromarketWarehouseStockSnapshotStore()
    empty_codes.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={},
        ),
    )
    app, _deps = _build_app_with_micromarket_loading_preview(
        execute_enabled=True,
        warehouse_stock_snapshot=empty_codes,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "—" in html
    launch_idx = html.index('name="launch_qty"')
    window = html[max(0, launch_idx - 200) : launch_idx + 250]
    assert 'value="3"' in window


def test_loading_tab_warehouse_batch_fail_uses_need_and_em_dash() -> None:
    # error: сбой batch МС → «—» и launch от need
    app, _deps = _build_app_with_micromarket_loading_preview(
        execute_enabled=True,
        move_gateway=_WarehouseFailGateway(warehouse={"2311": Decimal("5")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "—" in html
    launch_idx = html.index('name="launch_qty"')
    window = html[max(0, launch_idx - 200) : launch_idx + 250]
    assert 'value="3"' in window


def test_loading_tab_shelf_fallback_is_polka_kit_not_gruppa() -> None:
    # edge: нет имени в снимке → «Полка Kit #id», не «группа N»
    app, _deps = _build_app(
        seed_shelves=True,
        kit_groups=(),
        execute_enabled=True,
        move_gateway=_FakeMoveGateway(warehouse={"2311": Decimal("7"), "2312": Decimal("4")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "Полка Kit #10" in html
    assert "группа 10" not in html


def test_assembly_order_create_list_print_and_cancel() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("10")},
        )
    )
    assembly = InMemoryMicromarketAssemblyOrderStore()
    app, deps = _build_app(
        seed_preview=True,
        assembly_order_store=assembly,
        execute_enabled=True,
        warehouse_stock_snapshot=stock,
        move_gateway=_FakeMoveGateway(warehouse={"2311": Decimal("10")}),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    create = client.post(
        "/admin/machines/701/micromarket-assembly-orders",
        data={"product_code": "2311", "assembly_qty": "2"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert "tab=loading" in create.headers["location"]
    open_orders = assembly.list_open_for_machine("701")
    assert len(open_orders) == 1
    order_id = open_orders[0].order_id
    assert f"order={order_id}" in create.headers["location"]
    listed = client.get("/admin/micromarket-planograms/701?tab=loading")
    assert listed.status_code == 200
    assert order_id in listed.text
    assert 'id="micromarket-assembly-load-form"' in listed.text
    assert "Позиций" in listed.text
    printed = client.get(f"/admin/machines/701/micromarket-assembly-orders/{order_id}/print")
    assert printed.status_code == 200
    assert "2311" in printed.text
    assert "order_id=" in printed.text
    cancelled = client.post(
        f"/admin/machines/701/micromarket-assembly-orders/{order_id}/cancel",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    assert assembly.list_open_for_machine("701") == ()


def test_assembly_load_empty_session_shows_message() -> None:
    app, _deps = _build_app_with_micromarket_loading_preview(
        cycle_store=_MemoryCycleStore(),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-assembly-orders/load",
        headers={"Origin": "http://testserver"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "empty_session" in response.text
    assert "admin-error-cause" in response.text
    assert "Нет открытых ордеров" in response.text


def test_loading_reject_shows_cause_and_code() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("1")},
        )
    )
    app, _deps = _build_app(
        seed_preview=True,
        execute_enabled=True,
        warehouse_stock_snapshot=stock,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-assembly-orders",
        headers={"Origin": "http://testserver"},
        data={
            "product_code": "2311",
            "assembly_qty": "99",
            "stock_qty": "0",
            "target_qty": "5",
            "need_qty": "5",
            "launch_qty": "0",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "qty_above_available" in response.text
    assert "admin-error-cause" in response.text
    assert "admin-field-invalid" in response.text
    assert response.text.strip() != "qty_above_available"


def test_assembly_qty_prefills_min_need_and_warehouse() -> None:
    # happy: need=3 (target5−shelf2), warehouse=2 → assembly_qty=2
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("2")},
        )
    )
    app, _deps = _build_app(
        seed_preview=True,
        execute_enabled=True,
        warehouse_stock_snapshot=stock,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert 'name="assembly_qty"' in html
    qty_idx = html.index('name="assembly_qty"')
    qty_window = html[qty_idx : qty_idx + 220]
    assert 'value="2"' in qty_window
    assert "📦" not in html


def test_assembly_qty_prefills_need_when_warehouse_degraded() -> None:
    # edge: warehouse None → prefill need (3)
    app, _deps = _build_app(seed_preview=True, execute_enabled=False)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert 'name="assembly_qty"' in html
    qty_idx = html.index('name="assembly_qty"')
    qty_window = html[qty_idx : qty_idx + 220]
    assert 'value="3"' in qty_window


def test_assembly_qty_locked_when_sku_in_open_order() -> None:
    # happy: occupied SKU → disabled stepper + 📦, no assembly_qty submit field
    assembly = InMemoryMicromarketAssemblyOrderStore()
    assembly.save(
        MicromarketAssemblyOrder(
            order_id="ao-lock-1",
            machine_code="701",
            lines=(MicromarketAssemblyOrderLine(catalog_code="2311", qty=Decimal("1")),),
            created_at=_FROZEN_NOW,
        )
    )
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("10")},
        )
    )
    app, _deps = _build_app(
        seed_preview=True,
        assembly_order_store=assembly,
        execute_enabled=True,
        warehouse_stock_snapshot=stock,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert response.status_code == 200
    html = _assembly_panel_html(response.text)
    assert "📦" in html
    assert "admin-qty-stepper-locked" in html
    assert 'type="hidden" name="assembly_qty" value="0"' in html
    assert "admin-qty-input" not in html
    create = client.post(
        "/admin/machines/701/micromarket-assembly-orders",
        data={"product_code": "2311", "assembly_qty": "2"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 200
    assert len(assembly.list_open_for_machine("701")) == 1


def test_assembly_second_order_when_first_sku_locked_above() -> None:
    assembly = InMemoryMicromarketAssemblyOrderStore()
    assembly.save(
        MicromarketAssemblyOrder(
            order_id="ao-lock-1",
            machine_code="701",
            lines=(MicromarketAssemblyOrderLine(catalog_code="2311", qty=Decimal("1")),),
            created_at=_FROZEN_NOW,
        )
    )
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
            refreshed_at=_FROZEN_NOW,
            qty_by_catalog_code={"2311": Decimal("10"), "2312": Decimal("10")},
        )
    )
    app, _deps = _build_app(
        seed_shelves=True,
        assembly_order_store=assembly,
        execute_enabled=True,
        warehouse_stock_snapshot=stock,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    from urllib.parse import urlencode

    body = urlencode(
        [
            ("product_code", "2311"),
            ("assembly_qty", "0"),
            ("product_code", "2312"),
            ("assembly_qty", "2"),
        ]
    )
    create = client.post(
        "/admin/machines/701/micromarket-assembly-orders",
        content=body,
        headers={
            "Origin": "http://testserver",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        follow_redirects=False,
    )
    assert create.status_code == 303
    open_orders = assembly.list_open_for_machine("701")
    assert len(open_orders) == 2
    second = next(order for order in open_orders if order.order_id != "ao-lock-1")
    assert tuple(line.catalog_code for line in second.lines) == ("2312",)
    assert second.lines[0].qty == Decimal("2")
