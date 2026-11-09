from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.base_margin_commands import (
    BaseMarginCommandRejected,
    SaveBaseMargin,
)
from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore


def _now() -> datetime:
    return datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _cmd(store: InMemoryMatrixBaseMarginStore, audit: InMemoryMasterDataStores) -> SaveBaseMargin:
    return SaveBaseMargin(
        store=store,
        audit_stores=audit,
        now_factory=_now,
        scale_price_min_bound=Decimal("10"),
        scale_price_max_bound=Decimal("500"),
        scale_rate_min_bound=Decimal("0.1"),
        scale_rate_max_bound=Decimal("2.0"),
        curvature_min=Decimal("0.5"),
        curvature_max=Decimal("3"),
        margin_floor_min=Decimal("10"),
        margin_floor_max=Decimal("100"),
    )


def test_save_base_margin_rejects_unordered_prices() -> None:
    store = InMemoryMatrixBaseMarginStore()
    cmd = _cmd(store, InMemoryMasterDataStores())
    bad = curved_margin_params(scale_price_min=Decimal("100"), scale_price_max=Decimal("10"))
    with pytest.raises(BaseMarginCommandRejected) as exc:
        cmd.execute(params=bad, actor_telegram_user_id=1)
    assert exc.value.code == "scale_price_out_of_bounds"
    assert store.get() is None


def test_save_base_margin_rejects_curvature_oob() -> None:
    store = InMemoryMatrixBaseMarginStore()
    cmd = _cmd(store, InMemoryMasterDataStores())
    bad = curved_margin_params(curvature=Decimal("0.1"))
    with pytest.raises(BaseMarginCommandRejected) as exc:
        cmd.execute(params=bad, actor_telegram_user_id=1)
    assert exc.value.code == "curvature_out_of_bounds"
    assert store.get() is None


def test_save_base_margin_allows_none_rounding() -> None:
    store = InMemoryMatrixBaseMarginStore()
    audit = InMemoryMasterDataStores()
    params = curved_margin_params(rounding_last_digits=None)
    _cmd(store, audit).execute(params=params, actor_telegram_user_id=1)
    assert store.get() == params


def test_save_base_margin_persists_and_audits() -> None:
    store = InMemoryMatrixBaseMarginStore()
    audit = InMemoryMasterDataStores()
    params = curved_margin_params(rounding_last_digits=frozenset({0, 5}))
    _cmd(store, audit).execute(params=params, actor_telegram_user_id=42)
    assert store.get() == params
    records = audit.audit.list_all()
    assert records[0].command == "save_matrix_base_margin"
    assert records[0].actor_telegram_user_id == 42
