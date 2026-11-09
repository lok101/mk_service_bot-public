from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pymongo import MongoClient

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.infrastructure.composition import readiness as readiness_module
from src.infrastructure.composition.readiness import (
    ReadinessProbe,
    resolve_reference_data_readiness,
)
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)

_SID = ReferenceDataSourceId.BOT_USERS
_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def test_reference_data_freshness_reports_stale() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    stale = _NOW - timedelta(seconds=10_000)
    store.put(
        ReferenceDataSnapshot(
            source_id=_SID,
            rows=(("id",),),
            content_hash="sha256:x",
            last_fetched_at=stale,
            content_updated_at=stale,
        )
    )
    probe = ReadinessProbe(
        mongo_client=None,
        redis_client=None,
        reference_data_store=store,
        reference_data_source_ids=(_SID,),
        reference_data_staleness_seconds=1800,
        reference_data_now=lambda: _NOW,
    )
    freshness = probe.reference_data_freshness()
    assert freshness[_SID.value]["stale"] is True


def test_readiness_ms_catalog_staleness_only_when_enabled() -> None:
    sheets = (ReferenceDataSourceId.PRODUCT_VITRINE,)
    off_ids, off_staleness = resolve_reference_data_readiness(
        sheets,
        product_catalog_ms_sync_enabled=False,
        sheets_staleness_seconds=1800,
        ms_staleness_seconds=7200,
    )
    assert ReferenceDataSourceId.PRODUCT_CATALOG not in off_ids
    assert off_staleness == 1800

    on_ids, on_staleness = resolve_reference_data_readiness(
        sheets,
        product_catalog_ms_sync_enabled=True,
        sheets_staleness_seconds=1800,
        ms_staleness_seconds=7200,
    )
    assert ReferenceDataSourceId.PRODUCT_CATALOG in on_ids
    assert on_staleness == 7200

    store = InMemoryReferenceDataSnapshotStore()
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
            rows=(("code", "name", "entity_kind"),),
            content_hash="sha256:x",
            last_fetched_at=_NOW - timedelta(seconds=10_000),
            content_updated_at=_NOW - timedelta(seconds=10_000),
        ),
    )
    probe_off = ReadinessProbe(
        mongo_client=None,
        redis_client=None,
        reference_data_store=store,
        reference_data_source_ids=off_ids,
        reference_data_staleness_seconds=off_staleness,
        reference_data_now=lambda: _NOW,
    )
    assert "product_catalog" not in probe_off.reference_data_freshness()

    probe_on = ReadinessProbe(
        mongo_client=None,
        redis_client=None,
        reference_data_store=store,
        reference_data_source_ids=on_ids,
        reference_data_staleness_seconds=on_staleness,
        reference_data_now=lambda: _NOW,
    )
    freshness = probe_on.reference_data_freshness()
    assert freshness["product_catalog"]["stale"] is True


def test_build_readiness_probe_gates_ms_catalog_on_sync_enabled() -> None:
    source = inspect.getsource(ProcessRuntime._build_readiness_probe)
    assert "resolve_reference_data_readiness" in source
    assert "sync_enabled" in source


def test_readiness_ignores_matrix_worker_status() -> None:
    source = inspect.getsource(readiness_module)
    assert "matrix_worker_status" not in source

    without_worker = ReadinessProbe(mongo_client=None, redis_client=None)
    assert without_worker.mongo_ok() is True
    assert without_worker.redis_ok() is True
    assert without_worker.outbox_failed_count() == 0
    assert without_worker.reference_data_freshness() == {}
    assert "matrix_worker_status" not in without_worker.__dataclass_fields__


def test_readiness_mongo_ok_does_not_touch_matrix_worker_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = inspect.getsource(readiness_module)
    assert "matrix_worker_status" not in source

    accessed_collections: list[str] = []
    client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )

    def fake_ping(command: str, *_args: object, **_kwargs: object) -> dict[str, float]:
        assert command == "ping"
        return {"ok": 1.0}

    monkeypatch.setattr(client, "admin", SimpleNamespace(command=fake_ping))

    def tracking_getitem(_self: MongoClient[dict[str, Any]], _database_name: str) -> object:
        class _TrackingDatabase:
            def __getitem__(self, collection_name: str) -> object:
                accessed_collections.append(collection_name)
                if collection_name == "matrix_worker_status":
                    raise RuntimeError(
                        "matrix_worker_status must not be read by app readiness",
                    )
                return object()

        return _TrackingDatabase()

    monkeypatch.setattr(MongoClient, "__getitem__", tracking_getitem)

    probe = ReadinessProbe(mongo_client=client, redis_client=None)
    assert probe.mongo_ok() is True
    assert probe.redis_ok() is True
    assert probe.outbox_failed_count() == 0
    assert probe.reference_data_freshness() == {}
    assert accessed_collections == []
