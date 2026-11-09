from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.infrastructure.composition.factories.admin_http_deps import (
    build_snapshot_kit_product_groups_loader,
)
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    InMemoryKitShopReferenceSnapshotStore,
    KitShopReferenceSnapshot,
    KitShopSnapshotGroup,
)


def _snap(*, refreshed_at: datetime) -> KitShopReferenceSnapshot:
    return KitShopReferenceSnapshot(
        kit_company_id=42,
        refreshed_at=refreshed_at,
        groups=(KitShopSnapshotGroup(group_id=6267, group_name="Напитки"),),
        shops=(),
        products=(),
    )


def test_snapshot_loader_returns_groups_without_http() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    store.replace(_snap(refreshed_at=datetime.now(tz=UTC)))
    load = build_snapshot_kit_product_groups_loader(
        store=store,
        kit_company_id=42,
        stale_after_seconds=7200.0,
    )
    loaded = load()
    assert loaded.error == ""
    assert loaded.groups == ((6267, "Напитки"),)
    assert loaded.warning == ""


def test_snapshot_loader_cold_start_error() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    load = build_snapshot_kit_product_groups_loader(
        store=store,
        kit_company_id=42,
        stale_after_seconds=7200.0,
    )
    loaded = load()
    assert loaded.error == "Группы Kit Shop ещё не загружены"
    assert loaded.groups == ()


def test_snapshot_loader_stale_warning_nonblocking() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    store.replace(
        _snap(refreshed_at=datetime.now(tz=UTC) - timedelta(seconds=10_000)),
    )
    now = datetime.now(tz=UTC)
    load = build_snapshot_kit_product_groups_loader(
        store=store,
        kit_company_id=42,
        stale_after_seconds=7200.0,
        clock=lambda: now,
    )
    loaded = load()
    assert loaded.error == ""
    assert loaded.groups == ((6267, "Напитки"),)
    assert "устарел" in loaded.warning
