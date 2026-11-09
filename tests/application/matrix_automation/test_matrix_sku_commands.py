from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.matrix_automation.matrix_sku_commands import (
    BulkSaveMatrixSku,
    BulkSaveMatrixSkuInput,
    BulkSaveMatrixSkuRow,
    EnrollMatrixSku,
    EnrollMatrixSkuInput,
    MatrixSkuCommandRejected,
    SaveMatrixSku,
    SaveMatrixSkuInput,
)


def _now() -> datetime:
    return datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_enroll_seeds_name_and_default_multiplier() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("MS Name", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    cmd.execute(
        EnrollMatrixSkuInput(
            product_code="P1",
            capacity=5,
            product_multiplier=None,
            actor_telegram_user_id=42,
        )
    )
    got = catalog.get("P1")
    assert got == MatrixSkuCatalogEntry(
        product_code="P1",
        display_name="MS Name",
        capacity=5,
        product_multiplier=Decimal("1"),
    )


def test_enroll_rejects_unknown_sellable() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="NOPE",
                capacity=1,
                product_multiplier=None,
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "unknown_sellable_code"


def test_enroll_rejects_duplicate() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="X",
            capacity=1,
            product_multiplier=Decimal("1"),
        ),
    )
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("MS", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="P1",
                capacity=2,
                product_multiplier=None,
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "duplicate_product_code"


def test_enroll_rejects_non_product_kind() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"B1": ("Bundle", "bundle")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="B1",
                capacity=1,
                product_multiplier=None,
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "sellable_not_product"


def test_enroll_allows_capacity_zero() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("Name", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    ).execute(
        EnrollMatrixSkuInput(
            product_code="P1",
            capacity=0,
            product_multiplier=None,
            actor_telegram_user_id=1,
        )
    )
    got = catalog.get("P1")
    assert got is not None
    assert got.capacity == 0


def test_enroll_rejects_capacity_negative() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("N", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="P1",
                capacity=-1,
                product_multiplier=None,
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_capacity"


def test_enroll_rejects_empty_display_name() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("  ", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="P1",
                capacity=1,
                product_multiplier=None,
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_display_name"


def test_enroll_rejects_multiplier_oob() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("N", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            EnrollMatrixSkuInput(
                product_code="P1",
                capacity=1,
                product_multiplier=Decimal("9"),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "product_multiplier_out_of_bounds"


def test_enroll_appends_audit() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = EnrollMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        sellable_by_code={"P1": ("N", "product")},
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    cmd.execute(
        EnrollMatrixSkuInput(
            product_code="P1",
            capacity=3,
            product_multiplier=None,
            actor_telegram_user_id=7,
        )
    )
    records = master.audit.list_all()
    assert len(records) == 1
    assert records[0].command == "enroll_matrix_sku"
    assert records[0].payload["product_code"] == "P1"


def test_save_updates_fields_keeps_code() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    cmd.execute(
        SaveMatrixSkuInput(
            product_code="P1",
            display_name="New",
            capacity=9,
            product_multiplier=Decimal("1.1"),
            actor_telegram_user_id=3,
        )
    )
    got = catalog.get("P1")
    assert got is not None
    assert got.product_code == "P1"
    assert got.display_name == "New"
    assert got.capacity == 9
    assert got.product_multiplier == Decimal("1.1")


def test_save_rejects_missing() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            SaveMatrixSkuInput(
                product_code="NO",
                display_name="X",
                capacity=1,
                product_multiplier=Decimal("1"),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "missing_product_code"


def test_save_appends_audit() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    cmd.execute(
        SaveMatrixSkuInput(
            product_code="P1",
            display_name="New",
            capacity=2,
            product_multiplier=Decimal("1"),
            actor_telegram_user_id=3,
        )
    )
    assert master.audit.list_all()[0].command == "save_matrix_sku"


def test_save_allows_capacity_zero() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=5,
            product_multiplier=Decimal("1"),
        )
    )
    SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    ).execute(
        SaveMatrixSkuInput(
            product_code="P1",
            display_name="Old",
            capacity=0,
            product_multiplier=Decimal("1"),
            actor_telegram_user_id=1,
        )
    )
    got = catalog.get("P1")
    assert got is not None
    assert got.capacity == 0


def test_save_rejects_capacity_negative() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            SaveMatrixSkuInput(
                product_code="P1",
                display_name="Old",
                capacity=-1,
                product_multiplier=Decimal("1"),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_capacity"


def test_save_rejects_empty_name() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            SaveMatrixSkuInput(
                product_code="P1",
                display_name="  ",
                capacity=1,
                product_multiplier=Decimal("1"),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_display_name"


def test_save_rejects_multiplier_oob() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    cmd = SaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            SaveMatrixSkuInput(
                product_code="P1",
                display_name="Old",
                capacity=1,
                product_multiplier=Decimal("9"),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "product_multiplier_out_of_bounds"


def test_bulk_save_upserts_new_and_existing() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="OLD",
            display_name="Old",
            capacity=2,
            product_multiplier=Decimal("1"),
        )
    )
    master = InMemoryMasterDataStores()
    BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    ).execute(
        BulkSaveMatrixSkuInput(
            rows=(
                BulkSaveMatrixSkuRow(
                    product_code="OLD",
                    display_name="Old2",
                    capacity=3,
                    product_multiplier=Decimal("1.1"),
                ),
                BulkSaveMatrixSkuRow(
                    product_code="NEW",
                    display_name="New",
                    capacity=0,
                    product_multiplier=Decimal("1"),
                ),
            ),
            allowed_codes=frozenset({"OLD", "NEW"}),
            actor_telegram_user_id=7,
        )
    )
    old = catalog.get("OLD")
    new = catalog.get("NEW")
    assert old is not None and old.display_name == "Old2"
    assert new is not None and new.capacity == 0
    assert [row.command for row in master.audit.list_all()] == [
        "save_matrix_sku",
        "save_matrix_sku",
    ]


def test_bulk_save_rejects_code_not_in_allowed() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="X",
                        display_name="n",
                        capacity=0,
                        product_multiplier=Decimal("1"),
                    ),
                ),
                allowed_codes=frozenset({"Y"}),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "unknown_snack_code"


def test_bulk_save_rejects_capacity_negative() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="OLD",
                        display_name="n",
                        capacity=-1,
                        product_multiplier=Decimal("1"),
                    ),
                ),
                allowed_codes=frozenset({"OLD"}),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_capacity"


def test_bulk_save_rejects_empty_display_name() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="OLD",
                        display_name="  ",
                        capacity=0,
                        product_multiplier=Decimal("1"),
                    ),
                ),
                allowed_codes=frozenset({"OLD"}),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_display_name"


def test_bulk_save_invalid_row_does_not_persist_any_row() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    catalog.upsert(
        MatrixSkuCatalogEntry(
            product_code="GOOD",
            display_name="Good",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="GOOD",
                        display_name="Mutated",
                        capacity=2,
                        product_multiplier=Decimal("1"),
                    ),
                    BulkSaveMatrixSkuRow(
                        product_code="BAD",
                        display_name="Bad",
                        capacity=-1,
                        product_multiplier=Decimal("1"),
                    ),
                ),
                allowed_codes=frozenset({"GOOD", "BAD"}),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "invalid_capacity"
    got = catalog.get("GOOD")
    assert got is not None
    assert got.display_name == "Good"
    assert got.capacity == 1
    assert master.audit.list_all() == ()


def test_bulk_save_rejects_multiplier_oob() -> None:
    catalog = InMemoryMatrixSkuCatalogStore()
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(MatrixSkuCommandRejected) as ei:
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="OLD",
                        display_name="n",
                        capacity=0,
                        product_multiplier=Decimal("9"),
                    ),
                ),
                allowed_codes=frozenset({"OLD"}),
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "product_multiplier_out_of_bounds"


def test_bulk_save_logs_applied_prefix_on_infrastructure_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("ERROR")

    class FlakyCatalog(InMemoryMatrixSkuCatalogStore):
        def upsert(self, entry: MatrixSkuCatalogEntry) -> None:
            if entry.product_code == "SECOND":
                raise RuntimeError("disk full")
            super().upsert(entry)

    catalog = FlakyCatalog()
    master = InMemoryMasterDataStores()
    cmd = BulkSaveMatrixSku(
        catalog=catalog,
        audit_stores=master,
        now_factory=_now,
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
    )
    with pytest.raises(RuntimeError, match="disk full"):
        cmd.execute(
            BulkSaveMatrixSkuInput(
                rows=(
                    BulkSaveMatrixSkuRow(
                        product_code="FIRST",
                        display_name="One",
                        capacity=0,
                        product_multiplier=Decimal("1"),
                    ),
                    BulkSaveMatrixSkuRow(
                        product_code="SECOND",
                        display_name="Two",
                        capacity=0,
                        product_multiplier=Decimal("1"),
                    ),
                ),
                allowed_codes=frozenset({"FIRST", "SECOND"}),
                actor_telegram_user_id=9,
            )
        )
    assert catalog.get("FIRST") is not None
    assert any(rec.message == "bulk_save_matrix_sku_partial" for rec in caplog.records)
