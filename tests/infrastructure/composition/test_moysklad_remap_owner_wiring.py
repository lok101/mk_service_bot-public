"""ADR-0083: Remap HTTP client only in effects process wiring."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.infrastructure.composition.matrix_worker_wiring.fakes import _enabled_settings

from src.config.moysklad import MoySkladSettings
from src.config.product_procurement_mirror import ProductProcurementMirrorSettings
from src.infrastructure.composition.factories.integrations import build_moysklad_client
from src.infrastructure.composition.factories.product_identity import (
    build_procurement_mirror_worker,
)
from src.infrastructure.composition.factories.technician_warehouse import (
    _UnavailableTechnicianWarehouseTransferReader,
    build_technician_warehouse_transfer_reader,
)
from src.infrastructure.composition.wiring.wire_matrix_worker import (
    build_purchase_attributes_reader,
)
from src.infrastructure.composition.wiring.wire_technician_warehouse import (
    wire_technician_warehouse,
)
from src.infrastructure.moysklad.purchase_prices.http_client import (
    MoySkladPurchasePricesHttpClient,
)
from src.infrastructure.product_identity.memory_store import MemoryDomainProductStore


def _moysklad_configured() -> MoySkladSettings:
    return MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        organization_id="00000000-0000-0000-0000-000000000001",
        project_id="00000000-0000-0000-0000-000000000002",
        main_store_id="00000000-0000-0000-0000-000000000003",
        http_max_in_flight=2,
    )


def test_build_moysklad_client_when_configured() -> None:
    # happy: factory still builds when token set (effects path)
    client = build_moysklad_client(_moysklad_configured())
    assert client is not None


def test_include_moysklad_http_false_skips_client_in_settlement_branch() -> None:
    # edge: composition gate — None when flag off (mirrors assemble process!="effects")
    include_moysklad_http = False
    client = build_moysklad_client(_moysklad_configured()) if include_moysklad_http else None
    assert client is None


def test_technician_warehouse_reader_unavailable_without_client() -> None:
    # happy / ADR-0083: None client → unavailable reader (no Remap HTTP)
    reader = build_technician_warehouse_transfer_reader(None)
    assert isinstance(reader, _UnavailableTechnicianWarehouseTransferReader)


def test_wire_technician_warehouse_source_has_no_auto_build() -> None:
    # edge: wire must not fallback-build Remap (assemble passes client only for effects)
    source = inspect.getsource(wire_technician_warehouse)
    assert "build_moysklad_client" not in source
    assert "moysklad_client" in source


def test_matrix_purchase_reader_never_builds_http_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: matrix-worker has no Remap client
    settings = _enabled_settings(tmp_path)
    settings.moysklad = _moysklad_configured()

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("from_settings must not run in matrix-worker")

    monkeypatch.setattr(MoySkladPurchasePricesHttpClient, "from_settings", boom)
    reader, close = build_purchase_attributes_reader(settings)
    close()
    assert reader is not None


def test_procurement_mirror_store_without_moysklad_http_for_app_reads(tmp_path: Path) -> None:
    # edge: app process — Remap off, but store remains for admin last-buy reads
    settings = _enabled_settings(tmp_path)
    settings.moysklad = _moysklad_configured()
    settings.product_procurement_mirror = ProductProcurementMirrorSettings.model_construct(
        enabled=True,
        supply_concurrency=2,
        sync_interval_seconds=60,
        attr_package_quantity_id="",
        attr_supplier_product_name_id="",
    )
    worker, store, sync, closer = build_procurement_mirror_worker(
        settings,
        domain_product_store=MemoryDomainProductStore(),
        mongo_client=None,
        include_moysklad_http=False,
    )
    closer()
    assert worker is None
    assert store is not None
    assert sync is None
