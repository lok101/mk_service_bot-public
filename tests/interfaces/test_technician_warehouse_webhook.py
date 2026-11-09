from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

import pytest
from fastapi.testclient import TestClient
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions import (
    FormSubmissionValidationError,
)
from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.outbox.handler_ids import SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID
from src.application.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    RevisionFormTokenPayload,
    TechnicianWarehouseInventoryTokenPayload,
    create_loading_form_token,
    create_revision_form_token,
    create_technician_warehouse_inventory_token,
    peek_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.composition.adapters.auto_reconcile_accept_hook import (
    AcceptWithAutoReconcileEnqueue,
)
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    WebhookPlaceholderBot,
    build_google_forms_webhook_app,
)

_REVISION_SECRET = "revision-secret"
_WAREHOUSE_SECRET = "warehouse-secret"
_TECHNICIAN_ID = TechnicianId("tech-1")
_TELEGRAM_USER_ID = 424242
_WEBHOOK_SECRET = "webhook-secret"
_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS = 300
_WAREHOUSE_WEBHOOK = "/webhooks/google-forms/technician-warehouse-inventory-submitted"


def _active_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


@dataclass
class _RecordingAccept:
    calls: int = 0

    def execute(self, **kwargs: object) -> object:
        self.calls += 1
        return MagicMock(event_id=MagicMock(value="evt-1"), technician_id=_TECHNICIAN_ID)


@dataclass
class _RecordingDirectChat:
    calls: int = 0

    async def notify(self, **kwargs: object) -> None:
        self.calls += 1


@dataclass
class _RecordingFormWorkflow:
    calls: int = 0

    async def notify(self, **kwargs: object) -> None:
        self.calls += 1


@dataclass
class _RecordingRevisionAccept:
    calls: int = 0

    def execute(self, **kwargs: object) -> object:
        self.calls += 1
        return MagicMock(
            event_id=MagicMock(value="evt-rev-1"),
            revision_id=MagicMock(value="rev-1"),
            technician_id=_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
        )


@dataclass
class _WebhookDeps:
    accept_warehouse: _RecordingAccept = field(default_factory=_RecordingAccept)
    accept_revision: _RecordingRevisionAccept = field(default_factory=_RecordingRevisionAccept)
    direct_chat: _RecordingDirectChat = field(default_factory=_RecordingDirectChat)
    form_workflow: _RecordingFormWorkflow = field(default_factory=_RecordingFormWorkflow)
    warehouse_error: Exception | None = None
    bot_user: SystemUser | None = field(default_factory=_active_technician)


def _deps_case(**overrides: object) -> tuple[GoogleFormsWebhookDeps, _WebhookDeps]:
    case = _WebhookDeps()
    for key, value in overrides.items():
        setattr(case, key, value)
    if case.warehouse_error is not None:
        case.accept_warehouse.execute = MagicMock(side_effect=case.warehouse_error)  # type: ignore[method-assign]
    return _build_google_forms_webhook_deps_for_test(case), case


def _deps(**overrides: object) -> GoogleFormsWebhookDeps:
    deps, _case = _deps_case(**overrides)
    return deps


def _build_google_forms_webhook_deps_for_test(
    case: _WebhookDeps,
    *,
    verify_warehouse_token=verify_technician_warehouse_inventory_token,
) -> GoogleFormsWebhookDeps:
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = case.bot_user
    return GoogleFormsWebhookDeps(
        accept_revision_form_submission=case.accept_revision,
        accept_technician_warehouse_inventory=case.accept_warehouse,
        accept_inventory_form_submission=UnusedAcceptInventory(),  # type: ignore[arg-type]
        form_workflow_notifier=FormWorkflowNotifierRef(case.form_workflow),
        direct_warehouse_chat_notifier=case.direct_chat,
        telegram_user_resolver=resolver,
        bot=WebhookPlaceholderBot(),
        token_field_name="Код заявки.",
        webhook_secret=_WEBHOOK_SECRET,
        webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
        revision_form_token_secret=_REVISION_SECRET,
        inventory_form_token_secret="inventory-secret",
        technician_warehouse_inventory_form_token_secret=_WAREHOUSE_SECRET,
        verify_revision_form_token=verify_revision_form_token,
        verify_inventory_form_token=verify_inventory_form_token,
        verify_technician_warehouse_inventory_token=verify_warehouse_token,
        peek_form_token=peek_form_token,
    )


@dataclass(frozen=True, slots=True)
class UnusedAcceptInventory:
    def execute_loading(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("loading webhook must not be called")


def _warehouse_token(body: str = "body", *, secret: str = _WAREHOUSE_SECRET) -> str:
    return create_technician_warehouse_inventory_token(
        TechnicianWarehouseInventoryTokenPayload(
            technician_id=_TECHNICIAN_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce=body,
        ),
        secret,
    )


def _revision_token() -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="rev-1",
        ),
        _REVISION_SECRET,
    )


def _loading_token_on_revision_secret() -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="load-cross",
        ),
        _REVISION_SECRET,
    )


def _loading_token_on_warehouse_secret() -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="load-on-wh",
        ),
        _WAREHOUSE_SECRET,
    )


def _expired_warehouse_token() -> str:
    return create_technician_warehouse_inventory_token(
        TechnicianWarehouseInventoryTokenPayload(
            technician_id=_TECHNICIAN_ID,
            issued_at=datetime(2020, 1, 1, 9, 0, tzinfo=UTC),
            nonce="expired",
        ),
        _WAREHOUSE_SECRET,
    )


def _verify_warehouse_token_with_ttl(token: str, secret: str) -> object:
    return verify_technician_warehouse_inventory_token(token, secret, max_age_hours=1.0)


def _post_revision_endpoint(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    hidden_token: str | None = None,
) -> object:
    client = TestClient(build_google_forms_webhook_app(deps))
    hidden = hidden_token or token
    payload = {
        "form_id": "form-revision",
        "submitted_at": datetime(2026, 5, 20, 10, 0, tzinfo=UTC).isoformat(),
        "revision_token": token,
        "answers": [{"title": "Код заявки.", "value": hidden}],
    }
    return post_signed_webhook(
        client,
        "/webhooks/google-forms/revision-submitted",
        payload=payload,
        secret=deps.webhook_secret,
    )


def _post_warehouse_endpoint(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    hidden_token: str | None = None,
) -> object:
    client = TestClient(build_google_forms_webhook_app(deps))
    hidden = hidden_token or token
    payload = {
        "form_id": "form-wh-1",
        "submitted_at": datetime(2026, 5, 20, 10, 0, tzinfo=UTC).isoformat(),
        "token": token,
        "answers": [{"title": "Код заявки.", "value": hidden}],
    }
    return post_signed_webhook(
        client,
        _WAREHOUSE_WEBHOOK,
        payload=payload,
        secret=deps.webhook_secret,
    )


def test_warehouse_inventory_webhook_accepts_on_dedicated_path() -> None:
    deps, case = _deps_case()
    app = build_google_forms_webhook_app(deps)
    client = TestClient(app)
    token = _warehouse_token(secret=_WAREHOUSE_SECRET)
    response = post_signed_webhook(
        client,
        _WAREHOUSE_WEBHOOK,
        payload={
            "form_id": "form-wh-1",
            "submitted_at": "2026-05-20T10:00:00+00:00",
            "token": token,
            "answers": [
                {"title": "Код заявки.", "value": token},
                {"title": "Кофе", "value": "6"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "technician_warehouse_inventory"
    assert body["event_id"] == "evt-1"
    assert body["technician_id"] == _TECHNICIAN_ID.value
    assert "machine_id" not in body
    assert "revision_id" not in body
    assert case.accept_warehouse.calls == 1
    assert case.direct_chat.calls == 0


def test_revision_endpoint_keeps_revision_route_unchanged() -> None:
    deps, case = _deps_case()
    response = _post_revision_endpoint(deps, token=_revision_token())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert "machine_id" in body
    assert "revision_id" in body
    assert case.accept_revision.calls == 1
    assert case.accept_warehouse.calls == 0


def test_warehouse_token_answer_mismatch_returns_422() -> None:
    deps, case = _deps_case()
    response = _post_warehouse_endpoint(
        deps,
        token=_warehouse_token("body"),
        hidden_token=_warehouse_token("hidden"),
    )
    assert response.status_code == 422
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0


def test_revision_token_is_rejected_by_explicit_warehouse_verifier() -> None:
    with pytest.raises(ValueError, match="purpose"):
        verify_technician_warehouse_inventory_token(_revision_token(), _REVISION_SECRET)


def test_cross_purpose_loading_token_on_revision_endpoint_notifies_direct_chat() -> None:
    deps, case = _deps_case()
    response = _post_revision_endpoint(deps, token=_loading_token_on_revision_secret())
    assert response.status_code == 422
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0


def test_warehouse_verify_value_error_after_peek_sends_sync_chat() -> None:
    case = _WebhookDeps()
    deps = _build_google_forms_webhook_deps_for_test(
        case,
        verify_warehouse_token=_verify_warehouse_token_with_ttl,
    )
    response = _post_warehouse_endpoint(deps, token=_expired_warehouse_token())
    assert response.status_code == 422
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0


def test_warehouse_validation_422_sends_sync_chat_without_form_workflow() -> None:
    deps, case = _deps_case(warehouse_error=FormSubmissionValidationError("bad quantity"))
    response = _post_warehouse_endpoint(deps, token=_warehouse_token())
    assert response.status_code == 422
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0


def test_warehouse_concurrency_409_sends_sync_chat_without_form_workflow() -> None:
    deps, case = _deps_case(
        warehouse_error=TechnicianWarehouseConcurrencyError(technician_id=_TECHNICIAN_ID),
    )
    response = _post_warehouse_endpoint(deps, token=_warehouse_token())
    assert response.status_code == 409
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0


@dataclass
class _RecordingPublisher:
    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _ProtocolAccept:
    calls: int = 0

    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> object:
        del form_id, submitted_at, form_token, token_payload, answers
        self.calls += 1
        raise AssertionError("accept must not be called under portion lock")


def test_webhook_portion_lock_returns_409_without_accept() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id=f"portion:{_TECHNICIAN_ID.value}:inv0:sync",
        handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        event_document={"event_id": f"portion:{_TECHNICIAN_ID.value}:inv0:sync"},
    )
    recording = _ProtocolAccept()
    wrapper = AcceptWithAutoReconcileEnqueue(
        inner=recording,
        outbox_store=store,
        publisher=_RecordingPublisher(),
        auto_reconcile_enabled=True,
        warehouse_repository=InMemoryTechnicianWarehouseRepository(
            event_store=InMemoryTechnicianWarehouseEventStore(),
        ),
    )
    deps, _case = _deps_case(accept_warehouse=wrapper)
    response = _post_warehouse_endpoint(deps, token=_warehouse_token())
    assert response.status_code == 409
    assert "active settlement portion" in str(response.json()["detail"])
    assert recording.calls == 0
    assert _case.direct_chat.calls == 1
    assert _case.form_workflow.calls == 0


def test_unpeekable_token_returns_422_without_chat() -> None:
    deps, case = _deps_case()
    response = _post_revision_endpoint(deps, token="broken")
    assert response.status_code == 422
    assert case.direct_chat.calls == 0
    assert case.form_workflow.calls == 0


def test_known_technician_without_bot_user_returns_http_error_only() -> None:
    deps, case = _deps_case(bot_user=None, warehouse_error=FormSubmissionValidationError("bad"))
    response = _post_warehouse_endpoint(deps, token=_warehouse_token())
    assert response.status_code == 422
    assert case.direct_chat.calls == 0
    assert case.form_workflow.calls == 0


def test_revision_submitted_rejects_warehouse_purpose_without_chat() -> None:
    deps, case = _deps_case()
    app = build_google_forms_webhook_app(deps)
    client = TestClient(app)
    # token signed with warehouse secret — revision peek with revision secret fails
    token = _warehouse_token(secret=_WAREHOUSE_SECRET)
    response = post_signed_webhook(
        client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-1",
            "submitted_at": "2026-05-20T10:00:00+00:00",
            "revision_token": token,
            "answers": [{"title": "Код заявки.", "value": token}],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 422
    assert case.accept_warehouse.calls == 0
    assert case.direct_chat.calls == 0


def test_revision_submitted_rejects_warehouse_token_even_if_peekable() -> None:
    deps, case = _deps_case()
    app = build_google_forms_webhook_app(deps)
    client = TestClient(app)
    token = _warehouse_token(secret=_REVISION_SECRET)  # peekable on revision
    response = post_signed_webhook(
        client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-1",
            "submitted_at": "2026-05-20T10:00:00+00:00",
            "revision_token": token,
            "answers": [{"title": "Код заявки.", "value": token}],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 422
    assert case.accept_warehouse.calls == 0
    # peeked tech → same invalid-purpose path as loading on revision (sync chat)
    assert case.direct_chat.calls == 1


def test_warehouse_path_rejects_foreign_secret_without_chat() -> None:
    deps, case = _deps_case()
    response = _post_warehouse_endpoint(
        deps,
        token=_warehouse_token(secret=_REVISION_SECRET),
    )
    assert response.status_code == 422
    assert case.accept_warehouse.calls == 0
    assert case.direct_chat.calls == 0


def test_warehouse_path_rejects_cross_purpose_with_chat() -> None:
    deps, case = _deps_case()
    response = _post_warehouse_endpoint(deps, token=_loading_token_on_warehouse_secret())
    assert response.status_code == 422
    assert case.accept_warehouse.calls == 0
    assert case.direct_chat.calls == 1
    assert case.form_workflow.calls == 0
