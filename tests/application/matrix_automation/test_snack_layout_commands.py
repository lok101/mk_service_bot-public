from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.application.matrix_automation.planogram_product_code import (
    kit_product_code,
    skipped_product_name,
)
from src.application.matrix_automation.snack_layout_commands import (
    CopySnackLayout,
    CopySnackLayoutInput,
    SaveSnackLayout,
    SaveSnackLayoutInput,
    SnackLayoutCommandRejected,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.matrix_automation.snack_planogram import (
    PlanogramAnchorCell,
    SnackPlanogramMerge,
)
from src.application.product_identity import DomainProduct
from src.domain.ids import MachineId


def _snack_product(
    domain_product_id: str,
    name: str,
    catalog_code: str | None,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=f"d-{domain_product_id}",
        name=name,
        catalog_code=catalog_code,
        hidden=False,
    )


def _now() -> datetime:
    return datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class _Snapshots:
    def __init__(self, *, has: bool) -> None:
        self._has = has

    def has_unit_snapshot(self, *, machine_code: str, logical_matrix_name: str) -> bool:
        del machine_code, logical_matrix_name
        return self._has

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        del machine_code, logical_matrix_name, line_number
        return None

    def list_latest_for_machine(self, *, machine_code: str) -> tuple[object, ...]:
        del machine_code
        return ()

    def save(self, document: object) -> None:
        del document


def _snapshots_ok() -> _Snapshots:
    return _Snapshots(has=True)


def _save_input(
    *,
    machine_code: str = "514",
    matrix_multiplier: Decimal = Decimal("1"),
    auto_sync_enabled: bool = True,
    shelf_count: int = 6,
    slots_per_shelf: int = 10,
    merges: tuple[SnackPlanogramMerge, ...] = (),
    anchors: tuple[PlanogramAnchorCell, ...] = (),
    actor_telegram_user_id: int = 1,
) -> SaveSnackLayoutInput:
    return SaveSnackLayoutInput(
        machine_code=machine_code,
        matrix_multiplier=matrix_multiplier,
        auto_sync_enabled=auto_sync_enabled,
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        merges=merges,
        anchors=anchors,
        actor_telegram_user_id=actor_telegram_user_id,
    )


def test_save_snack_layout_persists_desired_with_qty() -> None:
    """qty>0 не блокирует save desired (stock вне команды)."""
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M514",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(12, "OLD"),),
        )
    )
    audit_stores = InMemoryMasterDataStores()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=audit_stores,
        now_factory=_now,
        known_product_codes=frozenset({"NEW", "OLD"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            matrix_multiplier=Decimal("1.1"),
            auto_sync_enabled=True,
            anchors=(PlanogramAnchorCell(0, 0, 12, "NEW"),),
            actor_telegram_user_id=1,
        )
    )
    got = layouts.get("514")
    assert got is not None
    assert got.cells == (SnackMachineLayoutCell(12, "NEW", 0, 0),)
    assert got.matrix_multiplier == Decimal("1.1")
    assert got.logical_matrix_name == "M514"


def test_save_snack_layout_rejects_duplicate_line() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="514",
                anchors=(
                    PlanogramAnchorCell(0, 0, 1, "A"),
                    PlanogramAnchorCell(0, 2, 1, "A"),
                ),
            )
        )
    assert exc.value.code == "duplicate_line_number"


def test_save_snack_layout_rejects_line_number_below_one() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="514",
                anchors=(PlanogramAnchorCell(0, 0, 0, "A"),),
            )
        )
    assert exc.value.code == "invalid_line_number"


def test_save_snack_layout_omits_empty_anchor_without_product() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 0, None),),
        )
    )
    got = layouts.get("514")
    assert got is not None
    assert got.cells == ()


def test_save_snack_layout_accepts_line_number_one() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    ).execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 1, "A"),),
        )
    )
    got = layouts.get("514")
    assert got is not None
    assert got.cells == (SnackMachineLayoutCell(1, "A", 0, 0),)


def test_save_snack_layout_rejects_unknown_product() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="514",
                anchors=(PlanogramAnchorCell(0, 0, 1, "UNKNOWN"),),
            )
        )
    assert exc.value.code == "unknown_product_code"


def test_save_new_archived_product_code_rejected() -> None:
    """error: новый archived product_code отклоняется."""
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"LIVE", "ARCH"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
        archived_product_codes=frozenset({"ARCH"}),
    )
    with pytest.raises(SnackLayoutCommandRejected) as ei:
        cmd.execute(
            _save_input(
                machine_code="514",
                anchors=(PlanogramAnchorCell(0, 0, 12, "ARCH"),),
            )
        )
    assert ei.value.code == "archived_product_code"
    assert "архив" in ei.value.message.lower() or "archived" in ei.value.message.lower()


def test_save_legacy_archived_cell_allowed() -> None:
    """happy: ARCH уже в existing layout — save разрешён."""
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M514",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(12, "ARCH"),),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"LIVE", "ARCH"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
        archived_product_codes=frozenset({"ARCH"}),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 12, "ARCH"),),
        )
    )
    got = layouts.get("514")
    assert got is not None
    assert got.cells == (SnackMachineLayoutCell(12, "ARCH", 0, 0),)


def test_save_snack_layout_rejects_multiplier_oob() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset(),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="514",
                matrix_multiplier=Decimal("9"),
            )
        )
    assert exc.value.code == "matrix_multiplier_out_of_bounds"


def test_save_snack_layout_writes_audit() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    audit_stores = InMemoryMasterDataStores()
    SaveSnackLayout(
        layouts=layouts,
        audit_stores=audit_stores,
        now_factory=_now,
        known_product_codes=frozenset(),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    ).execute(
        _save_input(
            machine_code="514",
            auto_sync_enabled=False,
            actor_telegram_user_id=42,
        )
    )
    records = list(audit_stores.audit.list_all())
    assert any(r.command == "save_snack_layout" for r in records)


def test_save_snack_layout_creates_when_missing() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    ).execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 1, "A"),),
        )
    )
    assert layouts.get("514") is not None
    assert layouts.get("514").logical_matrix_name == "514"


def test_copy_snack_layout_copies_cells_not_name() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="Name514",
            matrix_multiplier=Decimal("1.5"),
            auto_sync_enabled=False,
            cells=(SnackMachineLayoutCell(1, "A"),),
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="Name515",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("514"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("515"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    CopySnackLayout(
        layouts=layouts,
        machines=machines.machines,
        audit_stores=machines,
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
    ).execute(
        CopySnackLayoutInput(
            source_machine_code="514",
            dest_machine_code="515",
            actor_telegram_user_id=1,
        )
    )
    dest = layouts.get("515")
    assert dest is not None
    assert dest.logical_matrix_name == "Name515"
    assert dest.matrix_multiplier == Decimal("1.5")
    assert dest.auto_sync_enabled is False
    assert dest.cells == (SnackMachineLayoutCell(1, "A"),)


def test_copy_snack_layout_rejects_coffee_source() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="101",
            logical_matrix_name="C",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="S",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("515"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        CopySnackLayout(
            layouts=layouts,
            machines=stores.machines,
            audit_stores=stores,
            now_factory=_now,
            known_product_codes=frozenset(),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="101",
                dest_machine_code="515",
                actor_telegram_user_id=1,
            )
        )
    assert exc.value.code == "source_not_snack"


def test_copy_snack_layout_writes_audit() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="A",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, None),),
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="B",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    stores = InMemoryMasterDataStores()
    for mid in ("514", "515"):
        stores.machines.upsert(
            MasterMachine(
                machine_id=MachineId(mid),
                kind=MachineKind.SNACK,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            )
        )
    CopySnackLayout(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        known_product_codes=frozenset(),
    ).execute(
        CopySnackLayoutInput(
            source_machine_code="514",
            dest_machine_code="515",
            actor_telegram_user_id=7,
        )
    )
    records = list(stores.audit.list_all())
    assert any(r.command == "copy_snack_layout" for r in records)


def test_copy_snack_layout_rejects_empty_source_code() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    stores = InMemoryMasterDataStores()
    with pytest.raises(SnackLayoutCommandRejected) as ei:
        CopySnackLayout(
            layouts=layouts,
            machines=stores.machines,
            audit_stores=stores,
            now_factory=_now,
            known_product_codes=frozenset(),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="  ",
                dest_machine_code="515",
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "empty_copy_source"


def test_copy_rejects_same_machine() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="A",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("514"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        CopySnackLayout(
            layouts=layouts,
            machines=stores.machines,
            audit_stores=stores,
            now_factory=_now,
            known_product_codes=frozenset(),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="514",
                dest_machine_code="514",
                actor_telegram_user_id=1,
            )
        )
    assert exc.value.code == "copy_same_machine"


def test_copy_rejects_missing_source_layout() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="B",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    stores = InMemoryMasterDataStores()
    for mid in ("514", "515"):
        stores.machines.upsert(
            MasterMachine(
                machine_id=MachineId(mid),
                kind=MachineKind.SNACK,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            )
        )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        CopySnackLayout(
            layouts=layouts,
            machines=stores.machines,
            audit_stores=stores,
            now_factory=_now,
            known_product_codes=frozenset(),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="514",
                dest_machine_code="515",
                actor_telegram_user_id=1,
            )
        )
    assert exc.value.code == "source_layout_missing"


def test_copy_rejects_dest_not_snack() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="A",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "A"),),
        )
    )
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("514"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        CopySnackLayout(
            layouts=layouts,
            machines=stores.machines,
            audit_stores=stores,
            now_factory=_now,
            known_product_codes=frozenset({"A"}),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="514",
                dest_machine_code="101",
                actor_telegram_user_id=1,
            )
        )
    assert exc.value.code == "dest_not_snack"


def test_save_layout_allows_zero_capacity_when_sku_catalog_on() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"ZERO"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 1, "ZERO"),),
        )
    )
    saved = layouts.get("514")
    assert saved is not None
    assert saved.cells[0].product_code == "ZERO"


def test_save_layout_rejects_code_outside_snack_set() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"SNACK1"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as ei:
        cmd.execute(
            _save_input(
                machine_code="514",
                anchors=(PlanogramAnchorCell(0, 0, 1, "COFFEE"),),
            )
        )
    assert ei.value.code == "unknown_product_code"


def test_save_layout_allows_sellable_when_sku_catalog_off() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"SELLABLE_ONLY"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            anchors=(PlanogramAnchorCell(0, 0, 1, "SELLABLE_ONLY"),),
        )
    )
    assert layouts.get("514") is not None


def test_copy_layout_allows_zero_capacity_when_sku_catalog_on() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("514"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("515"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "ZERO"),),
        )
    )
    CopySnackLayout(
        layouts=layouts,
        machines=machines.machines,
        audit_stores=machines,
        now_factory=_now,
        known_product_codes=frozenset({"ZERO"}),
    ).execute(
        CopySnackLayoutInput(
            source_machine_code="514",
            dest_machine_code="515",
            actor_telegram_user_id=1,
        )
    )
    dest = layouts.get("515")
    assert dest is not None
    assert dest.cells[0].product_code == "ZERO"


def test_copy_layout_rejects_code_outside_snack_set() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("514"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    machines.machines.upsert(
        MasterMachine(
            machine_id=MachineId("515"),
            kind=MachineKind.SNACK,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="M",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "COFFEE"),),
        )
    )
    with pytest.raises(SnackLayoutCommandRejected) as ei:
        CopySnackLayout(
            layouts=layouts,
            machines=machines.machines,
            audit_stores=machines,
            now_factory=_now,
            known_product_codes=frozenset({"SNACK1"}),
        ).execute(
            CopySnackLayoutInput(
                source_machine_code="514",
                dest_machine_code="515",
                actor_telegram_user_id=1,
            )
        )
    assert ei.value.code == "unknown_product_code"


def test_save_rejects_auto_sync_without_snapshot() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    audit = InMemoryMasterDataStores()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=audit,
        now_factory=_now,
        known_product_codes=frozenset({"NEW"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_Snapshots(has=False),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="514",
                auto_sync_enabled=True,
                anchors=(PlanogramAnchorCell(0, 0, 1, "NEW"),),
            )
        )
    assert exc.value.code == "auto_sync_requires_apply"
    assert layouts.get("514") is None


def test_save_allows_auto_sync_with_snapshot() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    audit = InMemoryMasterDataStores()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=audit,
        now_factory=_now,
        known_product_codes=frozenset({"NEW"}),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_Snapshots(has=True),
    )
    cmd.execute(
        _save_input(
            machine_code="514",
            auto_sync_enabled=True,
            anchors=(PlanogramAnchorCell(0, 0, 1, "NEW"),),
        )
    )
    got = layouts.get("514")
    assert got is not None
    assert got.auto_sync_enabled is True


def test_save_snack_layout_rejects_shrink_with_data_outside_bounds() -> None:
    """Integration Save path maps shrink violation to SnackLayoutCommandRejected."""
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="512",
            logical_matrix_name="512",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
            shelf_count=6,
            slots_per_shelf=10,
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="512",
                auto_sync_enabled=False,
                shelf_count=5,
                anchors=(PlanogramAnchorCell(5, 0, 1, "A"),),
            )
        )
    assert exc.value.code == "planogram_shrink_blocked"


def test_save_snack_layout_allows_shrink_when_dropped_slots_empty() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="512",
            logical_matrix_name="512",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
            shelf_count=6,
            slots_per_shelf=10,
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="512",
            auto_sync_enabled=False,
            shelf_count=5,
            anchors=(PlanogramAnchorCell(0, 0, 11, "A"),),
        )
    )
    saved = layouts.get("512")
    assert saved is not None
    assert saved.shelf_count == 5
    assert saved.cells == (SnackMachineLayoutCell(11, "A", 0, 0),)


def test_save_snack_layout_shrink_auto_drops_empty_oob_merge() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="512",
            logical_matrix_name="512",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
            shelf_count=6,
            slots_per_shelf=12,
            merges=(SnackPlanogramMerge(0, 10),),
        )
    )
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset(),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="512",
            auto_sync_enabled=False,
            slots_per_shelf=10,
            merges=(SnackPlanogramMerge(0, 10),),
            anchors=(),
        )
    )
    saved = layouts.get("512")
    assert saved is not None
    assert saved.slots_per_shelf == 10
    assert saved.merges == ()


def test_save_snack_layout_rejects_duplicate_line_from_anchors() -> None:
    """Regression: duplicate line_number among projected cells."""
    layouts = InMemorySnackMachineLayoutStore()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A", "B"}),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    with pytest.raises(SnackLayoutCommandRejected) as exc:
        cmd.execute(
            _save_input(
                machine_code="512",
                auto_sync_enabled=False,
                anchors=(
                    PlanogramAnchorCell(0, 0, 11, "A"),
                    PlanogramAnchorCell(1, 0, 11, "B"),
                ),
            )
        )
    assert exc.value.code == "duplicate_line_number"


def test_save_snack_layout_persists_planogram_fields() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="512",
            auto_sync_enabled=False,
            slots_per_shelf=12,
            merges=(SnackPlanogramMerge(4, 0),),
            anchors=(PlanogramAnchorCell(4, 0, 11, "A"),),
        )
    )
    saved = layouts.get("512")
    assert saved is not None
    assert saved.slots_per_shelf == 12
    assert saved.merges == (SnackPlanogramMerge(4, 0),)
    assert saved.cells == (SnackMachineLayoutCell(11, "A", 4, 0),)


def test_save_snack_layout_merge_drops_right_anchor() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    cmd = SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset({"A", "B"}),
        matrix_multiplier_min=Decimal("0.1"),
        matrix_multiplier_max=Decimal("10"),
        snapshots=_snapshots_ok(),
    )
    cmd.execute(
        _save_input(
            machine_code="512",
            auto_sync_enabled=False,
            merges=(SnackPlanogramMerge(0, 0),),
            anchors=(
                PlanogramAnchorCell(0, 0, 11, "A"),
                PlanogramAnchorCell(0, 1, 12, "B"),
            ),
        )
    )
    saved = layouts.get("512")
    assert saved is not None
    assert saved.merges == (SnackPlanogramMerge(0, 0),)
    assert saved.cells == (SnackMachineLayoutCell(11, "A", 0, 0),)


def test_copy_snack_layout_copies_planogram_geometry() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="512",
            logical_matrix_name="M512",
            matrix_multiplier=Decimal("1.5"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(11, "A"),),
            shelf_count=6,
            slots_per_shelf=12,
            merges=(SnackPlanogramMerge(4, 0),),
        )
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="KEEP515",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
        )
    )
    machines = InMemoryMasterDataStores()
    for mid in ("512", "515"):
        machines.machines.upsert(
            MasterMachine(
                machine_id=MachineId(mid),
                kind=MachineKind.SNACK,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            )
        )
    CopySnackLayout(
        layouts=layouts,
        machines=machines.machines,
        audit_stores=machines,
        now_factory=_now,
        known_product_codes=frozenset({"A"}),
    ).execute(
        CopySnackLayoutInput(
            source_machine_code="512",
            dest_machine_code="515",
            actor_telegram_user_id=1,
        )
    )
    copied = layouts.get("515")
    assert copied is not None
    assert copied.logical_matrix_name == "KEEP515"
    assert copied.slots_per_shelf == 12
    assert copied.merges == (SnackPlanogramMerge(4, 0),)
    assert copied.cells == (SnackMachineLayoutCell(11, "A"),)


def test_copy_snack_layout_preserves_cell_coords() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    source_cells = (
        SnackMachineLayoutCell(11, "A", 0, 0),
        SnackMachineLayoutCell(19, "B", 0, 7),
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="src",
            logical_matrix_name="src",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=source_cells,
        ),
    )
    layouts.upsert(
        SnackMachineLayout(
            machine_code="dest",
            logical_matrix_name="dest",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
        ),
    )
    stores = InMemoryMasterDataStores()
    for mid in ("src", "dest"):
        stores.machines.upsert(
            MasterMachine(
                machine_id=MachineId(mid),
                kind=MachineKind.SNACK,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            )
        )
    CopySnackLayout(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=UTC),
        known_product_codes=frozenset({"A", "B"}),
    ).execute(
        CopySnackLayoutInput(
            source_machine_code="src",
            dest_machine_code="dest",
            actor_telegram_user_id=1,
        ),
    )
    dest = layouts.get("dest")
    assert dest is not None
    assert dest.cells == source_cells


def test_snack_cell_chip_code_empty_without_catalog_link() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Кефир", None))
    cell = SnackMachineLayoutCell(
        line_number=1,
        product_code=None,
        domain_product_id="prod-1",
    )
    assert kit_product_code(cell, products) is None
    assert skipped_product_name(cell, products) == "Кефир"


def test_snack_cell_chip_code_is_live_catalog_code() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Кефир", "2311"))
    cell = SnackMachineLayoutCell(
        line_number=1,
        product_code=None,
        domain_product_id="prod-1",
    )
    assert kit_product_code(cell, products) == "2311"
    assert skipped_product_name(cell, products) is None


def test_snack_cell_chip_code_keeps_legacy_product_code() -> None:
    cell = SnackMachineLayoutCell(line_number=1, product_code="2311")
    assert kit_product_code(cell, FakeDomainProductStore()) == "2311"


def test_save_snack_cell_accepts_domain_product_without_catalog_code() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Кефир", None))
    layouts = InMemorySnackMachineLayoutStore()
    SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset(),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
        products=products,
    ).execute(
        _save_input(
            auto_sync_enabled=False,
            anchors=(PlanogramAnchorCell(0, 0, 1, None, "prod-1"),),
        )
    )
    cell = layouts.get("514").cells[0]
    assert cell.domain_product_id == "prod-1"
    assert cell.product_code is None


def test_save_snack_layout_allows_same_domain_product_on_two_cells() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Кефир", None))
    layouts = InMemorySnackMachineLayoutStore()
    SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=frozenset(),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
        products=products,
    ).execute(
        _save_input(
            auto_sync_enabled=False,
            anchors=(
                PlanogramAnchorCell(0, 0, 1, None, "prod-1"),
                PlanogramAnchorCell(0, 1, 2, None, "prod-1"),
            ),
        )
    )
    saved = layouts.get("514")
    assert saved is not None
    assert len(saved.cells) == 2
    assert saved.cells[0].domain_product_id == "prod-1"
    assert saved.cells[1].domain_product_id == "prod-1"


def _save_with_products(
    layouts: InMemorySnackMachineLayoutStore,
    products: FakeDomainProductStore,
    *,
    archived: frozenset[str] = frozenset(),
    known: frozenset[str] = frozenset({"2311"}),
) -> SaveSnackLayout:
    return SaveSnackLayout(
        layouts=layouts,
        audit_stores=InMemoryMasterDataStores(),
        now_factory=_now,
        known_product_codes=known,
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snapshots=_snapshots_ok(),
        archived_product_codes=archived,
        products=products,
    )


def test_save_snack_cell_rejects_archived_catalog_code() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Старое", "9001"))
    layouts = InMemorySnackMachineLayoutStore()
    with pytest.raises(SnackLayoutCommandRejected, match="archived") as caught:
        cmd = _save_with_products(
            layouts, products, archived=frozenset({"9001"}), known=frozenset()
        )
        cmd.execute(
            _save_input(
                auto_sync_enabled=False,
                anchors=(PlanogramAnchorCell(0, 0, 1, None, "prod-1"),),
            )
        )
    assert caught.value.code == "archived_product_code"
    assert layouts.get("514") is None


def test_save_snack_cell_keeps_legacy_product_code_checks() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    _save_with_products(layouts, FakeDomainProductStore()).execute(
        _save_input(
            auto_sync_enabled=False,
            anchors=(PlanogramAnchorCell(0, 0, 1, "2311", None),),
        )
    )
    cell = layouts.get("514").cells[0]
    assert cell.domain_product_id is None
    assert cell.product_code == "2311"
    assert cell.shelf_index == 0
    assert cell.slot_index == 0


def test_save_snack_cell_maps_legacy_code_to_domain_product() -> None:
    products = FakeDomainProductStore()
    products.insert(_snack_product("prod-1", "Кефир", "2311"))
    layouts = InMemorySnackMachineLayoutStore()
    _save_with_products(layouts, products).execute(
        _save_input(
            auto_sync_enabled=False,
            anchors=(PlanogramAnchorCell(0, 0, 1, "2311", None),),
        )
    )
    cell = layouts.get("514").cells[0]
    assert cell.domain_product_id == "prod-1"
    assert cell.product_code is None


def test_save_snack_cell_rejects_unknown_domain_product_id() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    with pytest.raises(SnackLayoutCommandRejected) as caught:
        _save_with_products(layouts, FakeDomainProductStore(), known=frozenset()).execute(
            _save_input(
                auto_sync_enabled=False,
                anchors=(PlanogramAnchorCell(0, 0, 1, None, "missing"),),
            )
        )
    assert caught.value.code == "unknown_domain_product_id"
    assert layouts.get("514") is None
