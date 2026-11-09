from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.config.test_machine_pnl_settings import _stub_required_app_env

from src.application.reference_data import ReferenceDataProvider
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.composition.factories import (
    build_apply_snack_sale,
    build_product_spec_by_code_resolver,
    build_refresh_pending_with_accountability,
)


def test_build_product_spec_by_code_resolver_raises_when_catalog_missing() -> None:
    resolver = build_product_spec_by_code_resolver(ReferenceDataProvider())
    with pytest.raises(ValueError, match="Product spec not found for code"):
        resolver.resolve_by_code("missing")


def test_build_apply_snack_sale_returns_in_memory_backed_stock_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: без Mongo (settings по умолчанию не сконфигурирован) — in-memory fallback,
    # execute() работает end-to-end без исключений
    _stub_required_app_env(monkeypatch)
    settings = Settings()
    apply_snack_sale = build_apply_snack_sale(settings, mongo_client=None)

    sale = MachineSale(
        source_id="kv-1",
        machine_id=MachineId("129"),
        product_code="unknown-product",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    result = apply_snack_sale.execute(sale)

    assert result.resolve_status is not None


def test_build_refresh_pending_with_accountability_returns_no_op_on_empty_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: без Mongo — in-memory repo пуст, execute() не падает, ничего не переходит
    _stub_required_app_env(monkeypatch)
    settings = Settings()
    from tests.application.product_identity.fakes import FakeDomainProductStore

    refresh_pending = build_refresh_pending_with_accountability(
        settings,
        mongo_client=None,
        domain_product_store=FakeDomainProductStore(),
    )

    result = refresh_pending.execute(machine_id=MachineId("129"))

    assert result.transitioned_to_complete == ()
