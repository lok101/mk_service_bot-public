from __future__ import annotations

import pytest
from tests.config.test_machine_pnl_settings import _stub_required_app_env

from src.config.settings import Settings
from src.infrastructure.composition.factories import machine_pnl as machine_pnl_factory


class _StubUnitCostCatalog:
    """Minimal protocol-conforming stand-in for UnitCostCatalog (structural isinstance check)."""

    def get(self, product_code: str, *, as_of: object) -> None:
        return None


def _enable_machine_pnl(monkeypatch: pytest.MonkeyPatch, *, ttl_seconds: str = "100") -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "true")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SPREADSHEET_ID", "ss-unit")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SHEET_ID", "1")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID", "ss-opex")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SHEET_ID", "2")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID", "ss-rent")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SHEET_ID", "3")
    monkeypatch.setenv("MACHINE_PNL_CATALOG_CACHE_TTL_SECONDS", ttl_seconds)


def test_build_unit_cost_catalog_loader_caches_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: два вызова в пределах TTL -> Sheets read вызван 1 раз
    _enable_machine_pnl(monkeypatch, ttl_seconds="100")
    calls = {"n": 0}
    catalog_stub = _StubUnitCostCatalog()

    def fake_load_rows(**kwargs: object) -> list[list[str]]:
        calls["n"] += 1
        return [["sku", "unit_cost", "valid_from", "valid_to"]]

    monkeypatch.setattr(machine_pnl_factory, "load_unit_cost_sheet_rows", fake_load_rows)
    monkeypatch.setattr(
        machine_pnl_factory, "build_unit_cost_catalog_from_rows", lambda rows: catalog_stub
    )
    clock = {"now": 1_000.0}
    monkeypatch.setattr(machine_pnl_factory.time, "monotonic", lambda: clock["now"])

    loader = machine_pnl_factory.build_unit_cost_catalog_loader(Settings())
    first = loader()
    clock["now"] += 50
    second = loader()

    assert first is catalog_stub
    assert second is catalog_stub
    assert calls["n"] == 1


def test_build_unit_cost_catalog_loader_reloads_after_ttl_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # edge: после истечения TTL -> повторное чтение Sheets
    _enable_machine_pnl(monkeypatch, ttl_seconds="100")
    calls = {"n": 0}

    def fake_load_rows(**kwargs: object) -> list[list[str]]:
        calls["n"] += 1
        return [["sku", "unit_cost", "valid_from", "valid_to"]]

    monkeypatch.setattr(machine_pnl_factory, "load_unit_cost_sheet_rows", fake_load_rows)
    monkeypatch.setattr(
        machine_pnl_factory,
        "build_unit_cost_catalog_from_rows",
        lambda rows: _StubUnitCostCatalog(),
    )
    clock = {"now": 1_000.0}
    monkeypatch.setattr(machine_pnl_factory.time, "monotonic", lambda: clock["now"])

    loader = machine_pnl_factory.build_unit_cost_catalog_loader(Settings())
    loader()
    clock["now"] += 150
    loader()

    assert calls["n"] == 2


def test_build_opex_params_loader_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    # happy smoke: тот же _ttl_cached обёрнут вокруг opex loader
    _enable_machine_pnl(monkeypatch, ttl_seconds="100")
    calls = {"n": 0}

    def fake_load_rows(**kwargs: object) -> list[list[str]]:
        calls["n"] += 1
        return [
            [
                "valid_from",
                "labor_rate_global",
                "acquiring_percent",
                "acquiring_fee_per_sale",
                "terminal_monthly",
            ],
            ["2026-01-01", "50", "2,5", "0,2", "900"],
        ]

    monkeypatch.setattr(machine_pnl_factory, "load_global_opex_sheet_rows", fake_load_rows)
    clock = {"now": 2_000.0}
    monkeypatch.setattr(machine_pnl_factory.time, "monotonic", lambda: clock["now"])

    loader = machine_pnl_factory.build_opex_params_loader(Settings())
    loader()
    clock["now"] += 10
    loader()

    assert calls["n"] == 1


def test_build_location_rent_loader_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    # happy smoke: тот же _ttl_cached обёрнут вокруг rent loader
    _enable_machine_pnl(monkeypatch, ttl_seconds="100")
    calls = {"n": 0}

    def fake_load_rows(**kwargs: object) -> list[list[str]]:
        calls["n"] += 1
        return [
            ["Сумма", "Процент", "Id локации", "Id ТТ", "Имя", "Дата установки", "Дата снятия"],
            ["100", "", "loc-1", "101", "n", "01.05.2026", ""],
        ]

    monkeypatch.setattr(machine_pnl_factory, "load_location_rent_sheet_rows", fake_load_rows)
    clock = {"now": 3_000.0}
    monkeypatch.setattr(machine_pnl_factory.time, "monotonic", lambda: clock["now"])

    loader = machine_pnl_factory.build_location_rent_loader(Settings())
    loader()
    clock["now"] += 10
    loader()

    assert calls["n"] == 1
