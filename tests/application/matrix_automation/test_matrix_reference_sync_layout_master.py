from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.matrix_provider import make_provider

from src.application.matrix_automation.layout_parse import layouts_to_parse_state
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.matrix_automation.sync import MatrixReferenceSync, SyncGlobalAbort
from src.application.reference_data import ReferenceDataSourceId


class _FakeCatalog:
    def __init__(self) -> None:
        self.calls = 0

    def list_catalog_tabs(self) -> list[tuple[str, list[list[str]]]]:
        self.calls += 1
        return [("Tab", [["H1", "514"]])]


class _SnapStore:
    def get(self, source_id: ReferenceDataSourceId) -> None:
        return None


class _FakeUtility:
    def __init__(self) -> None:
        self.synced: list[ReferenceDataSourceId] = []
        self.store = _SnapStore()

    def sync_source(self, source_id: ReferenceDataSourceId) -> None:
        self.synced.append(source_id)


def test_sync_layout_master_skips_catalog_tabs() -> None:
    catalog = _FakeCatalog()
    utility = _FakeUtility()
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="Twin",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "A"),),
        )
    )
    sync = MatrixReferenceSync(
        utility_sync=utility,
        provider=make_provider(),
        catalog_reader=catalog,
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
        layout_master_enabled=True,
        layout_store=layouts,
    )
    state = sync.sync()
    assert not isinstance(state, SyncGlobalAbort)
    assert catalog.calls == 0
    assert len(state.enabled_matrices) == 1


def test_sync_layout_master_still_syncs_utility() -> None:
    utility = _FakeUtility()
    sync = MatrixReferenceSync(
        utility_sync=utility,
        provider=make_provider(),
        catalog_reader=_FakeCatalog(),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
        layout_master_enabled=True,
        layout_store=InMemorySnackMachineLayoutStore(),
    )
    sync.sync()
    assert utility.synced == [ReferenceDataSourceId.PRODUCT_MULTIPLIERS]


def test_sync_layout_master_off_reads_catalog_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _FakeCatalog()
    provider = make_provider()
    called: list[str] = []

    def _capture(_self: object, title: str, _rows: list[list[str]]) -> None:
        called.append(title)

    monkeypatch.setattr(type(provider), "apply_catalog_tab", _capture)
    sync = MatrixReferenceSync(
        utility_sync=_FakeUtility(),
        provider=provider,
        catalog_reader=catalog,
        utility_source_ids=(),
        layout_master_enabled=False,
        layout_store=None,
    )
    sync.sync()
    assert catalog.calls == 1
    assert called == ["Tab"]


def test_missing_layout_skips_unit_not_global_abort() -> None:
    store = InMemorySnackMachineLayoutStore()
    state = layouts_to_parse_state(store.list_all())
    assert state.enabled_matrices == ()
    result = MatrixReferenceSync(
        utility_sync=_FakeUtility(),
        provider=make_provider(),
        catalog_reader=_FakeCatalog(),
        utility_source_ids=(),
        layout_master_enabled=True,
        layout_store=store,
    ).sync()
    assert not isinstance(result, SyncGlobalAbort)
