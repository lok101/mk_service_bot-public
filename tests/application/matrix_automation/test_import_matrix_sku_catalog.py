from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.import_matrix_sku_catalog import (
    ImportMatrixSkuCatalog,
    ImportMatrixSkuCatalogInput,
)
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)


def _now() -> datetime:
    return datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_import_seeds_multipliers_and_layout_codes() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(
                SnackMachineLayoutCell(1, "FROM_LAYOUT"),
                SnackMachineLayoutCell(2, None),
            ),
        )
    )
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        multipliers={"FROM_SHEET": Decimal("1.2")},
        sheet_names={},
        ms_by_code={
            "FROM_SHEET": ("Sheet Name", 10),
            "FROM_LAYOUT": ("Layout Name", 4),
        },
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    result = cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=1))
    assert catalog.get("FROM_SHEET") == MatrixSkuCatalogEntry(
        product_code="FROM_SHEET",
        display_name="Sheet Name",
        capacity=10,
        product_multiplier=Decimal("1.2"),
    )
    assert catalog.get("FROM_LAYOUT") == MatrixSkuCatalogEntry(
        product_code="FROM_LAYOUT",
        display_name="Layout Name",
        capacity=4,
        product_multiplier=Decimal("1"),
    )
    assert result.imported_count == 2


def test_import_skips_bad_volume() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=None,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        multipliers={"BAD": Decimal("1")},
        sheet_names={},
        ms_by_code={"BAD": ("Name", 0)},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    result = cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=1))
    assert catalog.get("BAD") is None
    assert "BAD" in result.skipped_codes


def test_import_does_not_overwrite_existing() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="KEEP",
            display_name="Existing",
            capacity=99,
            product_multiplier=Decimal("2"),
        )
    )
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=None,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        multipliers={"KEEP": Decimal("1")},
        sheet_names={},
        ms_by_code={"KEEP": ("MS", 5)},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    result = cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=1))
    got = catalog.get("KEEP")
    assert got is not None
    assert got.capacity == 99
    assert "KEEP" in result.skipped_existing_codes


def test_import_skips_missing_name() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=None,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        multipliers={"NONAME": Decimal("1")},
        sheet_names={},
        ms_by_code={},  # no MS card
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    result = cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=1))
    assert catalog.get("NONAME") is None
    assert "NONAME" in result.skipped_codes


def test_import_uses_sheet_name_when_ms_missing() -> None:
    """Empty MS name → sheet_names fallback; capacity still from MS volume.

    Spec: capacity from MS volume. Without an MS card, skip (see
    `test_import_skips_missing_name`). With MS card present but empty name —
    use sheet name + MS capacity.
    """
    catalog = InMemoryMatrixSkuCatalogStore()
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=None,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        multipliers={"FALLBACK": Decimal("1")},
        sheet_names={"FALLBACK": "From Sheet"},
        ms_by_code={"FALLBACK": ("", 5)},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    result = cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=1))
    assert catalog.get("FALLBACK") == MatrixSkuCatalogEntry(
        product_code="FALLBACK",
        display_name="From Sheet",
        capacity=5,
        product_multiplier=Decimal("1"),
    )
    assert result.imported_count == 1


def test_import_appends_audit() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = ImportMatrixSkuCatalog(
        catalog=catalog,
        layouts=None,
        audit_stores=master,
        now_factory=_now,
        multipliers={"P1": Decimal("1")},
        sheet_names={},
        ms_by_code={"P1": ("N", 3)},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    cmd.execute(ImportMatrixSkuCatalogInput(actor_telegram_user_id=9))
    assert master.audit.list_all()[0].command == "import_matrix_sku_catalog"
