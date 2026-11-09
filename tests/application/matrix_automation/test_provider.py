from __future__ import annotations

from tests.application.matrix_automation.fixtures.matrix_provider import (
    CatalogReader,
    UtilitySync,
    catalog_tab,
    make_provider,
    seed_ms_name_to_code,
)

from src.application.matrix_automation import SyncGlobalAbort
from src.application.matrix_automation.sync import MatrixReferenceSync
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.domain.matrix_pricing.product_lookup import resolve_product_code


def test_duplicate_canonical_matrix_name_returns_global_abort() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    sync = MatrixReferenceSync(
        utility_sync=UtilitySync(provider),
        provider=provider,
        catalog_reader=CatalogReader(
            [
                ("Snacks ", catalog_tab()),
                (" Snacks", catalog_tab()),
            ],
        ),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert isinstance(result, SyncGlobalAbort)
    assert "duplicate logical_matrix_name" in result.reason


def test_ms_name_to_code_applied_before_catalog_tabs() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    provider.apply_catalog_tab("Snacks", catalog_tab())
    state = provider.build_parse_state()
    assert len(state.enabled_matrices) == 1
    assert state.enabled_matrices[0].cells[0].product_code == "MS-1"


def test_one_blocked_matrix_leaves_other_enabled() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    provider.apply_catalog_tab("Good", catalog_tab(machines="777"))
    unknown = catalog_tab()
    unknown[2][0] = "Missing product"
    unknown[3][0] = "1"
    provider.apply_catalog_tab("Unknown", unknown)
    state = provider.build_parse_state()
    assert len(state.enabled_matrices) == 1
    assert state.enabled_matrices[0].logical_matrix_name == "Good"
    assert len(state.blocked_matrices) == 1
    assert state.blocked_matrices[0].logical_matrix_name == "Unknown"


def test_auto_sync_disabled_matrices_counter() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    from src.application.matrix_automation.sheets.layout import AUTO_SYNC_COL

    disabled_tab = catalog_tab()
    disabled_tab[0][AUTO_SYNC_COL] = "FALSE"
    provider.apply_catalog_tab("Off", disabled_tab)
    provider.apply_catalog_tab("On", catalog_tab())
    state = provider.build_parse_state()
    assert state.auto_sync_disabled_matrices == 1
    assert len(state.enabled_matrices) == 1
    assert state.enabled_matrices[0].logical_matrix_name == "On"


def test_oob_product_multiplier_blocks_matrix_in_provider() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_MULTIPLIERS,
        [
            ["product_code", "product_name", "multiplier"],
            ["MS-1", "Кола 0.5", "5.0"],
        ],
    )
    provider.apply_catalog_tab("Snacks", catalog_tab())
    state = provider.build_parse_state()
    assert state.enabled_matrices == ()
    assert len(state.blocked_matrices) == 1
    assert state.blocked_matrices[0].deploy_reason == "product_reference_invalid"


def test_matrix_name_to_code_from_ms_catalog_strip_exact() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["c1", "Exact Name", "product"],
        ],
    )
    matrix = make_provider()
    matrix.set_name_to_code(provider.product_catalog().name_to_code)

    assert resolve_product_code("Exact Name", matrix.name_to_code).is_ok()
    assert resolve_product_code(" Exact Name ", matrix.name_to_code).is_ok()
    assert resolve_product_code("exact name", matrix.name_to_code).is_err()


def test_matrix_ignores_vitrine_text_aliases() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_VITRINE,
        [["id", "имя", "aliases"], ["c1", "Form", "AliasOnly"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [["code", "name", "entity_kind"], ["c1", "MS Name", "product"]],
    )
    matrix = make_provider()
    matrix.set_name_to_code(provider.product_catalog().name_to_code)

    assert resolve_product_code("AliasOnly", matrix.name_to_code).is_err()
    assert resolve_product_code("MS Name", matrix.name_to_code).is_ok()


def test_matrix_missing_ms_catalog_degraded_empty_name_to_code() -> None:
    matrix = make_provider()
    matrix.set_name_to_code({})
    assert matrix.name_to_code == {}
    matrix.apply_catalog_tab("Unknown", catalog_tab())
    state = matrix.build_parse_state()
    assert state.enabled_matrices == ()
    assert len(state.blocked_matrices) == 1
    assert state.blocked_matrices[0].logical_matrix_name == "Unknown"
