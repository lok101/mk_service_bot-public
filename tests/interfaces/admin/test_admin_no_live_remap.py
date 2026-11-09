"""ADR-0083: admin HTTP deps never build live Remap clients."""

from __future__ import annotations

import pytest
from tests.infrastructure.composition.test_admin_http_deps_factory import (
    _minimal_runtime_with_master_data,
)

from src.application.micromarket_loading.supply_order_category_facts_from_snapshot import (
    SupplyOrderCategoryFactsFromSnapshot,
)
from src.infrastructure.composition.factories.admin_http_deps import build_admin_http_deps
from src.infrastructure.micromarket_loading.ms_move import MoySkladMicromarketMoveClient
from src.infrastructure.micromarket_loading.outbox_move_gateway import OutboxMicromarketMoveGateway
from src.infrastructure.moysklad.supply_order_category_reader import (
    MoySkladSupplyOrderCategoryReader,
)


def test_admin_http_deps_has_no_live_remap_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: category facts from snapshot adapter; no live Remap readers/gateways
    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    settings.moysklad.api_token = settings.moysklad.api_token  # configured in fixture
    deps = build_admin_http_deps(runtime, settings)
    assert isinstance(deps.supply_order_category_facts, SupplyOrderCategoryFactsFromSnapshot)
    assert not isinstance(deps.supply_order_category_facts, MoySkladSupplyOrderCategoryReader)
    assert deps.micromarket_assortment_reader is None
    assert deps.snack_sku_assortment_reader is None
    gateway = deps.micromarket_loading_move_gateway
    assert gateway is None or isinstance(gateway, OutboxMicromarketMoveGateway)
    assert not isinstance(gateway, MoySkladMicromarketMoveClient)
