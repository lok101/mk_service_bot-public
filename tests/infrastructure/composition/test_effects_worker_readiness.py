from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from pymongo import MongoClient
from tests.interfaces.test_webhook_api_health import _webhook_deps

from src.application.outbox.handler_ids import NO_SALES_INCIDENT_CONTROL_HANDLER_ID
from src.config.effects_worker import EffectsWorkerSettings
from src.config.worker_liveness import WORKER_LIVENESS_TARGETS_V1
from src.infrastructure.alerting.worker_liveness_watchdog import WorkerLivenessWatchdog
from src.infrastructure.composition.effects_worker_container import EffectsWorkerContainer
from src.infrastructure.composition.effects_worker_heartbeat import (
    effects_worker_heartbeat_loop,
    record_effects_worker_heartbeat,
)
from src.infrastructure.composition.readiness import ReadinessProbe
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.interfaces.google_forms.webhook import build_google_forms_webhook_app

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _fail(store: InMemoryOutboxStore, handler_id: str) -> None:
    assert store.enqueue(
        event_id=f"evt-{handler_id}",
        handler_id=handler_id,
        event_document={"handler_id": handler_id},
    )
    claimed = store.claim_pending(limit=1, handler_id=handler_id)
    entry = claimed[0]
    store.mark_failed(
        str(entry["entry_id"]),
        claim_id=str(entry["claim_id"]),
        error_message="terminal",
        permanent=True,
    )


def _live_probe(
    store: InMemoryOutboxStore,
    monkeypatch: pytest.MonkeyPatch,
) -> ReadinessProbe:
    mongo = MongoClient("mongodb://127.0.0.1:1", serverSelectionTimeoutMS=1)
    monkeypatch.setattr(
        mongo,
        "admin",
        SimpleNamespace(command=lambda command, *_args, **_kwargs: {"ok": 1.0}),
    )
    redis_client = redis_lib.Redis(
        host="127.0.0.1",
        port=1,
        socket_connect_timeout=0.01,
    )
    monkeypatch.setattr(redis_client, "ping", lambda: True)
    return ReadinessProbe(
        mongo_client=mongo,
        redis_client=redis_client,
        outbox_admin=store,
    )


def test_liveness_allowlist_includes_effects_worker() -> None:
    by_name = {target.name: target.status_collection for target in WORKER_LIVENESS_TARGETS_V1}
    assert by_name["effects-worker"] == "effects_worker_status"
    assert len(WORKER_LIVENESS_TARGETS_V1) == 6


def test_effects_worker_status_collection_default_has_no_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGODB_EFFECTS_WORKER_STATUS_COLLECTION", raising=False)
    settings = EffectsWorkerSettings()
    assert settings.status_collection == "effects_worker_status"
    assert "enabled" not in EffectsWorkerSettings.model_fields
    monkeypatch.setenv(
        "MONGODB_EFFECTS_WORKER_STATUS_COLLECTION",
        "custom_effects_status",
    )
    assert EffectsWorkerSettings().status_collection == "custom_effects_status"


def test_ready_ignores_foreign_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryOutboxStore()
    _fail(store, "revision_telegram")
    probe = _live_probe(store, monkeypatch)
    app = build_google_forms_webhook_app(
        _webhook_deps(),
        readiness=probe,
        outbox_readiness_max_failed=0,
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_503_when_no_sales_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryOutboxStore()
    _fail(store, NO_SALES_INCIDENT_CONTROL_HANDLER_ID)
    probe = _live_probe(store, monkeypatch)
    app = build_google_forms_webhook_app(
        _webhook_deps(),
        readiness=probe,
        outbox_readiness_max_failed=0,
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["reason"] == "outbox_failed_entries"
    assert body["failed_count"] == 1


def test_missing_effects_heartbeat_alerts_from_app() -> None:
    matched = [target for target in WORKER_LIVENESS_TARGETS_V1 if target.name == "effects-worker"]
    assert matched
    target = matched[0]

    class _Collection:
        def find_one(self, filter: dict[str, Any]) -> None:
            assert filter == {"_id": "worker"}
            return None

    class _Database:
        def __getitem__(self, name: str) -> _Collection:
            assert name == target.status_collection
            return _Collection()

    sends: list[str] = []
    watchdog = WorkerLivenessWatchdog(
        targets=(target,),
        stale_seconds=300,
        alert_cooldown_seconds=1800,
        database=_Database(),
        send_alert=sends.append,
        now=lambda: datetime(2026, 10, 23, tzinfo=UTC),
    )
    watchdog.check_once()
    assert len(sends) == 1
    assert "effects-worker" in sends[0]
    assert "missing" in sends[0]
    assert target.status_collection in sends[0]


class _HeartbeatCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> None:
        self.calls.append((filter, update, upsert))


def test_effects_heartbeat_writes_worker_document() -> None:
    collection = _HeartbeatCollection()
    record_effects_worker_heartbeat(collection, at="2026-10-23T06:00:00+00:00")
    assert collection.calls == [
        (
            {"_id": "worker"},
            {
                "$set": {
                    "last_heartbeat_at": "2026-10-23T06:00:00+00:00",
                    "worker_enabled": True,
                },
            },
            True,
        ),
    ]
    assert (
        inspect.signature(effects_worker_heartbeat_loop).parameters["interval_seconds"].default
        == 60.0
    )
    run_source = inspect.getsource(EffectsWorkerContainer.run)
    assert "effects_worker_heartbeat_loop" in run_source


def test_effects_heartbeat_loop_retries_after_write_error() -> None:
    class _FailOnce:
        def __init__(self) -> None:
            self.calls = 0

        def update_one(
            self,
            filter: dict[str, Any],
            update: dict[str, Any],
            *,
            upsert: bool = False,
        ) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("mongo down")

    collection = _FailOnce()
    shutdown = asyncio.Event()

    async def _stop_after_second_write() -> None:
        while collection.calls < 2:
            await asyncio.sleep(0.01)
        shutdown.set()

    async def _scenario() -> None:
        await asyncio.gather(
            effects_worker_heartbeat_loop(
                collection,
                shutdown,
                interval_seconds=0.01,
                now=lambda: "2026-10-23T06:00:00+00:00",
            ),
            _stop_after_second_write(),
        )

    asyncio.run(_scenario())
    assert collection.calls >= 2


def test_watchdog_stays_on_ingress() -> None:
    ingress = inspect.getsource(ProcessRuntime._ingress_background_tasks)
    effects = inspect.getsource(ProcessRuntime._effects_background_tasks)
    assert "_run_worker_liveness_watchdog_until_shutdown" in ingress
    assert "_run_worker_liveness_watchdog_until_shutdown" not in effects


def test_env_examples_document_status_collection_without_enabled_flag() -> None:
    for name in (".env.dev.example", ".env.prod.example", ".env.e2e.example"):
        text = (_REPO_ROOT / name).read_text(encoding="utf-8")
        assert "MONGODB_EFFECTS_WORKER_STATUS_COLLECTION=effects_worker_status" in text
        assert "EFFECTS_WORKER_ENABLED" not in text
