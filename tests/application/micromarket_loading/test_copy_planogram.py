from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.master_data import InMemoryMasterDataStores, MachineKind, MachineStatus
from src.application.master_data.models import MasterMachine
from src.application.micromarket_loading import (
    CopyMicromarketPlanogram,
    CopyMicromarketPlanogramInput,
    MicromarketPlanogram,
    MicromarketPlanogramCopyRejected,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    ShopListPublishStatus,
)
from src.domain.ids import MachineId
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryMicromarketPlanogramStore

_NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _seed_machine(stores: InMemoryMasterDataStores, machine_id: str) -> None:
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId(machine_id),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )


def _source_doc() -> MicromarketPlanogram:
    return MicromarketPlanogram(
        machine_code="701",
        lines=(
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("189"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
        ),
        shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
        updated_at=_NOW,
        shop_list_status=ShopListPublishStatus.PUBLISHED,
        shop_list_publication_id="pub-1",
    )


def test_copy_planogram_overwrites_target_without_auto_publish() -> None:
    # happy: copy replaces dest lines; publish status resets; no auto-publish
    stores = InMemoryMasterDataStores()
    _seed_machine(stores, "701")
    _seed_machine(stores, "702")
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(_source_doc())
    planograms.upsert(
        MicromarketPlanogram(
            machine_code="702",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2312",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=100,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=100, sort_order=0),),
            updated_at=_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="old",
        )
    )
    CopyMicromarketPlanogram(
        store=planograms,
        machines=stores.machines,
        now_factory=lambda: _NOW,
    ).execute(
        CopyMicromarketPlanogramInput(
            source_machine_code="701",
            dest_machine_code="702",
        )
    )
    dest = planograms.get("702")
    assert dest is not None
    assert dest.lines[0].product_code == "2311"
    assert dest.lines[0].price_rub == Decimal("189")
    assert dest.shelves == (MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),)
    assert dest.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert dest.shop_list_publication_id == ""
    source = planograms.get("701")
    assert source is not None
    assert source.shop_list_status is ShopListPublishStatus.PUBLISHED


def test_copy_planogram_rejects_same_machine() -> None:
    # edge: source == target rejected
    stores = InMemoryMasterDataStores()
    _seed_machine(stores, "701")
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(_source_doc())
    with pytest.raises(MicromarketPlanogramCopyRejected) as exc:
        CopyMicromarketPlanogram(
            store=planograms,
            machines=stores.machines,
            now_factory=lambda: _NOW,
        ).execute(
            CopyMicromarketPlanogramInput(
                source_machine_code="701",
                dest_machine_code="701",
            )
        )
    assert exc.value.code == "copy_same_machine"


def test_copy_planogram_rejects_missing_source() -> None:
    # error: missing source planogram
    stores = InMemoryMasterDataStores()
    _seed_machine(stores, "701")
    _seed_machine(stores, "702")
    planograms = InMemoryMicromarketPlanogramStore()
    with pytest.raises(MicromarketPlanogramCopyRejected) as exc:
        CopyMicromarketPlanogram(
            store=planograms,
            machines=stores.machines,
            now_factory=lambda: _NOW,
        ).execute(
            CopyMicromarketPlanogramInput(
                source_machine_code="701",
                dest_machine_code="702",
            )
        )
    assert exc.value.code == "source_planogram_missing"


def test_copy_planogram_rejects_empty_source() -> None:
    stores = InMemoryMasterDataStores()
    _seed_machine(stores, "702")
    planograms = InMemoryMicromarketPlanogramStore()
    with pytest.raises(MicromarketPlanogramCopyRejected) as exc:
        CopyMicromarketPlanogram(
            store=planograms,
            machines=stores.machines,
            now_factory=lambda: _NOW,
        ).execute(
            CopyMicromarketPlanogramInput(
                source_machine_code="",
                dest_machine_code="702",
            )
        )
    assert exc.value.code == "empty_copy_source"
