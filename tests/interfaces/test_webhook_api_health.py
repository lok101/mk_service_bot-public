from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from tests.interfaces._warehouse_webhook_dep_fields import warehouse_webhook_dep_kwargs
from tests.interfaces.test_loading_webhook import (
    _StubRegisterLoadingFromForm,
    _UnusedAcceptRevision,
)

from src.application.form_submissions.accept import AcceptInventoryFormSubmissionService
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.config.worker_liveness import WORKER_LIVENESS_TARGETS_V1
from src.domain.form_tokens import verify_inventory_form_token
from src.infrastructure.composition.readiness import ReadinessProbe
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier


def _webhook_deps() -> GoogleFormsWebhookDeps:
    return GoogleFormsWebhookDeps(
        accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
        accept_inventory_form_submission=AcceptInventoryFormSubmissionService(
            form_submission_store=InMemoryFormSubmissionStore(),
            register_loading_from_form=_StubRegisterLoadingFromForm(),
            product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
            form_token_field_name="Код заявки.",
        ),
        form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
        token_field_name="Код заявки.",
        webhook_secret="webhook-secret",
        webhook_signature_max_age_seconds=300,
        revision_form_token_secret="revision-secret",
        inventory_form_token_secret="loading-secret",
        verify_revision_form_token=lambda token, secret: token,  # type: ignore[return-value]
        verify_inventory_form_token=verify_inventory_form_token,
        **warehouse_webhook_dep_kwargs(),
    )


@dataclass(frozen=True, slots=True)
class _HealthyReadiness:
    def mongo_ok(self) -> bool:
        return True

    def redis_ok(self) -> bool:
        return True

    def outbox_failed_count(self) -> int:
        return 0

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


@dataclass(frozen=True, slots=True)
class _FailingReadiness:
    def mongo_ok(self) -> bool:
        return False

    def redis_ok(self) -> bool:
        return True

    def outbox_failed_count(self) -> int:
        return 0

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


@dataclass(frozen=True, slots=True)
class _FailingRedisReadiness:
    def mongo_ok(self) -> bool:
        return True

    def redis_ok(self) -> bool:
        return False

    def outbox_failed_count(self) -> int:
        return 0

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


@dataclass(frozen=True, slots=True)
class _ProbeWithFailedOutbox:
    def mongo_ok(self) -> bool:
        return True

    def redis_ok(self) -> bool:
        return True

    def outbox_failed_count(self) -> int:
        return 2

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


@dataclass(frozen=True, slots=True)
class _ProbeWithFailedOutboxBelowThreshold:
    def mongo_ok(self) -> bool:
        return True

    def redis_ok(self) -> bool:
        return True

    def outbox_failed_count(self) -> int:
        return 2

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


@dataclass(frozen=True, slots=True)
class _ProbeWithFailedOutboxAndMongoDown:
    def mongo_ok(self) -> bool:
        return False

    def redis_ok(self) -> bool:
        return True

    def outbox_failed_count(self) -> int:
        return 1

    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        return {}


def test_health_ready_returns_ok_when_probe_healthy() -> None:
    app = build_google_forms_webhook_app(_webhook_deps(), readiness=_HealthyReadiness())
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "reference_data": {}}


def test_health_ready_returns_503_when_mongo_down() -> None:
    app = build_google_forms_webhook_app(_webhook_deps(), readiness=_FailingReadiness())
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reference_data": {}}


def test_health_ready_returns_503_when_outbox_has_failed_entries() -> None:
    app = build_google_forms_webhook_app(
        _webhook_deps(),
        readiness=_ProbeWithFailedOutbox(),
        outbox_readiness_max_failed=0,
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "outbox_failed_entries",
        "failed_count": 2,
        "reference_data": {},
    }


def test_health_ready_returns_ok_when_failed_outbox_within_threshold() -> None:
    app = build_google_forms_webhook_app(
        _webhook_deps(),
        readiness=_ProbeWithFailedOutboxBelowThreshold(),
        outbox_readiness_max_failed=5,
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "reference_data": {}}


def test_health_ready_outbox_failure_takes_priority_over_mongo_down() -> None:
    app = build_google_forms_webhook_app(
        _webhook_deps(),
        readiness=_ProbeWithFailedOutboxAndMongoDown(),
        outbox_readiness_max_failed=0,
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "outbox_failed_entries",
        "failed_count": 1,
        "reference_data": {},
    }


def test_health_ready_returns_503_when_redis_down() -> None:
    app = build_google_forms_webhook_app(_webhook_deps(), readiness=_FailingRedisReadiness())
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reference_data": {}}


def test_health_ready_ignores_worker_status(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_collections = {t.status_collection for t in WORKER_LIVENESS_TARGETS_V1}
    accessed_collections: list[str] = []
    client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )

    def fake_ping(command: str, *_args: object, **_kwargs: object) -> dict[str, float]:
        assert command == "ping"
        return {"ok": 1.0}

    monkeypatch.setattr(client, "admin", SimpleNamespace(command=fake_ping))

    def tracking_getitem(
        _self: MongoClient[dict[str, Any]],
        _database_name: str,
    ) -> object:
        class _TrackingDatabase:
            def __getitem__(self, collection_name: str) -> object:
                accessed_collections.append(collection_name)
                if collection_name in worker_collections:
                    raise RuntimeError(
                        f"{collection_name} must not be read by /health/ready",
                    )
                return object()

        return _TrackingDatabase()

    monkeypatch.setattr(MongoClient, "__getitem__", tracking_getitem)

    probe = ReadinessProbe(mongo_client=client, redis_client=None)
    response = TestClient(
        build_google_forms_webhook_app(_webhook_deps(), readiness=probe),
    ).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "reference_data": {}}
    assert accessed_collections == []
    assert worker_collections.isdisjoint(accessed_collections)


def test_health_ready_includes_reference_data_freshness() -> None:
    from datetime import UTC, datetime, timedelta

    store = InMemoryReferenceDataSnapshotStore()
    sid = ReferenceDataSourceId.BOT_USERS
    stale = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC) - timedelta(seconds=10_000)
    store.put(
        ReferenceDataSnapshot(
            source_id=sid,
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
        reference_data_source_ids=(sid,),
        reference_data_staleness_seconds=1800,
        reference_data_now=lambda: datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC),
    )
    app = build_google_forms_webhook_app(_webhook_deps(), readiness=probe)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["reference_data"][sid.value]["stale"] is True


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(build_google_forms_webhook_app(_webhook_deps()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_is_available_when_docs_enabled() -> None:
    client = TestClient(
        build_google_forms_webhook_app(_webhook_deps(), expose_openapi_docs=True),
    )

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "MK Service Bot API"


def test_openapi_is_hidden_when_docs_disabled() -> None:
    client = TestClient(
        build_google_forms_webhook_app(_webhook_deps(), expose_openapi_docs=False),
    )

    assert client.get("/health").status_code == 200
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
