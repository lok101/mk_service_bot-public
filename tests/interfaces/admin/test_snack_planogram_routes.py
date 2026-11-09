from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from tests.application.product_identity.fakes import FakeCatalogLookup
from tests.interfaces.admin.test_machine_layout_profile import (
    _authed_client,
    _planogram_post,
    _seed_machine,
    _seed_unit_snapshot,
    seed_snack_with_layout,
)
from tests.interfaces.admin.test_machine_layout_profile import (
    _build_app as layout_build_app,
)
from tests.interfaces.admin.test_planogram_panel_gates import (
    _build_app,
    _client,
    _signed_widget_fields,
)

from src.application.master_data import MachineKind, MachineStatus, MasterMachine
from src.application.matrix_automation import SnackMachineLayout, SnackMachineLayoutCell
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
)


def test_snack_list_shows_code_and_name_links() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    response = client.get("/admin/snack-planograms")
    assert response.status_code == 200
    text = response.text
    assert "<h1>Снеки</h1>" in text
    assert 'class="admin-roster"' in text
    assert 'class="sortable" data-sort-key="code"' in text
    assert 'class="sortable" data-sort-key="name"' in text
    assert 'href="/admin/snack-planograms/501"' in text
    assert ">501<" in text
    assert 'href="/admin/snack-planograms/701"' not in text
    assert "Скачать Excel" not in text
    assert "admin-save-bar" not in text
    assert 'id="snack-planograms-search"' in text
    assert "Показано" in text
    assert 'id="snack-planograms-visible-count"' in text
    assert 'id="snack-planograms-total-count"' in text


def test_snack_list_forbidden_for_keeper() -> None:
    # Roster-only panel bag без layout/planogram: нет snack list.
    # MASTER_DATA теперь → coordinator с micromarket_planograms (OM ISS-408).
    from tests.application.product_identity.fakes import FakeCatalogLookup
    from tests.interfaces.admin.test_planogram_panel_gates import _build_app

    from src.application.matrix_automation.snack_machine_layout_memory import (
        InMemorySnackMachineLayoutStore,
    )
    from src.infrastructure.product_identity import MemoryDomainProductStore
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketDeviceStockStore,
    )

    app, _deps = _build_app(
        panels=None,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
    )
    anon = TestClient(app)
    response = anon.get("/admin/snack-planograms", follow_redirects=False)
    assert response.status_code == 303


def test_snack_nav_item_for_operator() -> None:
    operator = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    list_html = operator.get("/admin/snack-planograms").text
    assert 'href="/admin/snack-planograms"' in list_html
    assert "Снеки" in list_html
    # Парк без планограммы: только ROSTER не логинится как полный coordinator
    # без MASTER_DATA bag; curator без парка не видит snack в machines.
    curator = _client(frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    assert curator.get("/admin/machines").status_code == 403


def test_snack_nav_hidden_without_layout() -> None:
    app, deps = _build_app(
        panels=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS, AdminPanel.DOMAIN_PRODUCTS}),
        machine_id="701",
        machine_kind=MachineKind.MICRO_MARKET,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=False,
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
    fridge = client.get("/admin/micromarket-planograms")
    assert fridge.status_code == 200
    assert "/admin/snack-planograms" not in fridge.text
    assert client.get("/admin/snack-planograms").status_code == 404


def test_snack_nav_and_list_without_fridge() -> None:
    app, deps = _build_app(
        panels=None,
        machine_id="501",
        machine_kind=MachineKind.SNACK,
        micromarket_stock_store=None,
        domain_product_store=None,
        catalog_product_lookup=None,
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
        attach_micromarket_planogram=False,
    )
    assert deps.master_stores is not None
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/snack-planograms")
    assert response.status_code == 200
    assert 'href="/admin/snack-planograms"' in response.text
    assert "Снеки" in response.text
    assert client.get("/admin/micromarket-planograms").status_code == 404


def test_snack_workspace_shows_layout_without_loading_tab() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    response = client.get("/admin/snack-planograms/501")
    assert response.status_code == 200
    text = response.text
    assert "<h1>501</h1>" in text
    assert 'href="/admin/snack-planograms">← Снеки</a>' in text
    assert 'id="machine-planogram-form"' in text or "_planogram_form" in text
    assert "admin-workspace-tab" not in text
    assert ">Загрузка<" not in text and ">Загрузка</" not in text
    assert "← Парк" not in text
    assert "← Профиль аппарата" not in text


def test_snack_workspace_fridge_or_missing_is_404() -> None:
    client = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    assert client.get("/admin/snack-planograms/701").status_code == 404
    assert client.get("/admin/snack-planograms/999").status_code == 404


def test_old_layout_gets_redirect_after_panel_check() -> None:
    operator = _client(frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}))
    response = operator.get("/admin/machines/501/layout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin/snack-planograms/501")
    from tests.application.product_identity.fakes import FakeCatalogLookup
    from tests.interfaces.admin.test_planogram_panel_gates import _build_app

    from src.application.matrix_automation.snack_machine_layout_memory import (
        InMemorySnackMachineLayoutStore,
    )
    from src.infrastructure.product_identity import MemoryDomainProductStore
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketDeviceStockStore,
    )

    app, _deps = _build_app(
        panels=None,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        domain_product_store=MemoryDomainProductStore(),
        catalog_product_lookup=FakeCatalogLookup(),
        layout_master_enabled=True,
        snack_layout_store=InMemorySnackMachineLayoutStore(),
    )
    anon = TestClient(app)
    for path in ("/admin/machines/501/layout", "/admin/snack-planograms/501"):
        forbidden = anon.get(path, follow_redirects=False)
        assert forbidden.status_code == 303, path


def test_snack_post_returns_to_workspace() -> None:
    app, deps, layouts, _stock = layout_build_app()
    snack_id = seed_snack_with_layout(deps, layouts, line=12, product="OLD")
    assert deps.matrix_price_snapshot_store is not None
    _seed_unit_snapshot(
        deps.matrix_price_snapshot_store,
        machine_code=snack_id.value,
        logical_matrix_name=f"M{snack_id.value}",
    )
    client = _authed_client(app)
    saved = client.post(
        f"/admin/machines/{snack_id.value}/layout",
        data=_planogram_post(
            anchors=[(0, 0, "12", "NEW", "New Product")],
            auto_sync_enabled=True,
        ),
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"].endswith(f"/admin/snack-planograms/{snack_id.value}")

    src_id = seed_snack_with_layout(deps, layouts, line=12, product="A")
    dest_id = seed_snack_with_layout(deps, layouts, line=1, product="B")
    copied = client.post(
        f"/admin/machines/{dest_id.value}/layout/copy",
        data={"source_machine_id": str(src_id.value)},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert copied.status_code == 303
    assert copied.headers["location"].endswith(f"/admin/snack-planograms/{dest_id.value}")

    apply_id = _seed_machine(deps, kind=MachineKind.SNACK)
    layouts.upsert(
        SnackMachineLayout(
            machine_code=apply_id.value,
            logical_matrix_name=apply_id.value,
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(SnackMachineLayoutCell(1, "SKU1"),),
        )
    )
    applied = client.post(
        f"/admin/machines/{apply_id.value}/layout/apply",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert applied.status_code == 303
    assert applied.headers["location"].endswith(f"/admin/snack-planograms/{apply_id.value}")
    assert "layout_error" not in (applied.headers["location"] or "")
