from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.application.matrix_automation.import_snack_layouts import (
    ImportSnackLayouts,
    ImportSnackLayoutsInput,
)
from src.application.matrix_automation.sheets.layout import (
    AUTO_SYNC_COL,
    BLOCK_COL_STEP,
    MACHINE_CODES_COL,
    MATRIX_MULTIPLIER_COL,
)
from src.application.matrix_automation.snack_machine_layout import SnackMachineLayout
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.domain.ids import MachineId

_HEADER_WIDTH = AUTO_SYNC_COL + 1


def _enabled_tab(
    *,
    auto_sync: str = "TRUE",
    multiplier: str = "1.0",
    machines: str = "512",
    blocks: tuple[tuple[int, str, str], ...] = ((0, "1", "Кола 0.5"), (BLOCK_COL_STEP, "2", "")),
) -> list[list[str]]:
    header = [""] * _HEADER_WIDTH
    header[MACHINE_CODES_COL] = machines
    header[MATRIX_MULTIPLIER_COL] = multiplier
    header[AUTO_SYNC_COL] = auto_sync
    max_col = max((col for col, _, _ in blocks), default=0) + 1
    width = max(_HEADER_WIDTH, max_col)
    product_row = [""] * width
    line_row = [""] * width
    for col, line, name in blocks:
        product_row[col] = name
        line_row[col] = line
    return [header, [], product_row, line_row]


def _now() -> datetime:
    return datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _snack(mid: str) -> MasterMachine:
    return MasterMachine(
        machine_id=MachineId(mid),
        kind=MachineKind.SNACK,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )


def test_import_snack_layouts_explodes_h1() -> None:
    rows = _enabled_tab(
        machines="514,515",
        blocks=((0, "1", "A"),),
    )
    layouts = InMemorySnackMachineLayoutStore()
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(_snack("514"))
    stores.machines.upsert(_snack("515"))
    result = ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(
        ImportSnackLayoutsInput(
            tabs=(("TwinTab", rows),),
            actor_telegram_user_id=1,
        )
    )
    assert result.noop is False
    assert layouts.get("514") is not None
    assert layouts.get("515") is not None
    assert layouts.get("514").logical_matrix_name == "TwinTab"
    assert layouts.get("515").logical_matrix_name == "TwinTab"


def test_import_snack_layouts_skips_non_snack() -> None:
    rows = _enabled_tab(machines="101", blocks=((0, "1", "A"),))
    layouts = InMemorySnackMachineLayoutStore()
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    result = ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(
        ImportSnackLayoutsInput(
            tabs=(("T", rows),),
            actor_telegram_user_id=1,
        )
    )
    assert "101" in result.skipped_codes
    assert layouts.count() == 0


def test_import_snack_layouts_resumes_missing_codes() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="kept",
            matrix_multiplier=Decimal("2"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(_snack("514"))
    stores.machines.upsert(_snack("515"))
    rows = _enabled_tab(machines="514,515", blocks=((0, "1", "A"),))
    result = ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(ImportSnackLayoutsInput(tabs=(("TwinTab", rows),), actor_telegram_user_id=1))
    assert result.noop is False
    assert "514" in result.skipped_existing_codes
    assert layouts.get("514") is not None
    assert layouts.get("514").logical_matrix_name == "kept"
    assert layouts.get("514").matrix_multiplier == Decimal("2")
    assert layouts.get("515") is not None


def test_import_snack_layouts_skips_existing_without_overwrite() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    from src.application.matrix_automation.snack_machine_layout import (
        SnackMachineLayoutCell,
    )

    layouts.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="kept",
            matrix_multiplier=Decimal("2"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "OLD"),),
        )
    )
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(_snack("514"))
    rows = _enabled_tab(machines="514", blocks=((0, "1", "A"),))
    ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(ImportSnackLayoutsInput(tabs=(("TwinTab", rows),), actor_telegram_user_id=1))
    saved = layouts.get("514")
    assert saved is not None
    assert saved.cells == (SnackMachineLayoutCell(1, "OLD"),)
    assert saved.logical_matrix_name == "kept"


def test_import_snack_layouts_writes_audit() -> None:
    rows = _enabled_tab(machines="514,515", blocks=((0, "1", "A"),))
    layouts = InMemorySnackMachineLayoutStore()
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(_snack("514"))
    stores.machines.upsert(_snack("515"))
    ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(
        ImportSnackLayoutsInput(
            tabs=(("TwinTab", rows),),
            actor_telegram_user_id=1,
        )
    )
    assert any(r.command == "import_snack_layouts" for r in stores.audit.list_all())


def test_import_snack_layouts_reports_blocked_and_conflicts() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(_snack("514"))
    stores.machines.upsert(_snack("515"))
    layouts = InMemorySnackMachineLayoutStore()
    good = _enabled_tab(machines="514", blocks=((0, "1", "A"),))
    blocked = _enabled_tab(machines="515", multiplier="", blocks=((0, "1", "A"),))
    duplicate = _enabled_tab(machines="514", blocks=((0, "1", "A"),))
    invalid_h1 = _enabled_tab(machines="", blocks=((0, "1", "A"),))
    result = ImportSnackLayouts(
        layouts=layouts,
        machines=stores.machines,
        audit_stores=stores,
        now_factory=_now,
        name_to_code={"A": "MS-A"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    ).execute(
        ImportSnackLayoutsInput(
            tabs=(
                ("GoodTab", good),
                ("BlockedTab", blocked),
                ("DupTab", duplicate),
                ("InvalidH1", invalid_h1),
            ),
            actor_telegram_user_id=1,
        )
    )
    assert "BlockedTab" in result.blocked_tabs
    assert "InvalidH1" in result.blocked_tabs
    assert "514" in result.conflict_codes
    assert layouts.get("514") is not None
