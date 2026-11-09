from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import create_autospec

from fastapi.testclient import TestClient
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.domain.form_tokens import (
    SnackInventoryFormTokenPayload,
    create_snack_inventory_form_token,
    peek_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
    verify_snack_inventory_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.domain.form_tokens.codec import _base64_urlsafe_encode, _sign
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    WebhookPlaceholderBot,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier

_WEBHOOK_SECRET = "webhook-secret"
_NOW_SECRET = "snack-now-secret"
_AS_OF_SECRET = "snack-as-of-secret"
_TECHNICIAN_ID = TechnicianId("tech-snack")
_TELEGRAM_USER_ID = 515151
_MACHINE = "514"
_CELL = (_MACHINE, "SnackA", 1)
_SUBMITTED_AT = datetime(2026, 7, 2, 15, 0, tzinfo=UTC)
_NOW_WEBHOOK = "/webhooks/google-forms/snack-inventory-now-submitted"
_AS_OF_WEBHOOK = "/webhooks/google-forms/snack-inventory-as-of-submitted"
_TOKEN_FIELD = "Код заявки."


@dataclass
class _RecordingAccept:
    calls: int = 0
    last_kwargs: dict[str, object] = field(default_factory=dict)

    def execute(self, **kwargs: object) -> None:
        self.calls += 1
        self.last_kwargs = dict(kwargs)


@dataclass
class _RecordingDirectChat:
    calls: int = 0

    async def notify(self, **kwargs: object) -> None:
        self.calls += 1


@dataclass(frozen=True, slots=True)
class _UnusedAcceptRevision:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("revision accept must not be called")


@dataclass(frozen=True, slots=True)
class _UnusedAcceptInventory:
    def execute_loading(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("loading accept must not be called")


@dataclass(frozen=True, slots=True)
class _UnusedAcceptWarehouse:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("warehouse accept must not be called")


def _active_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-snack"),
        name="Snack Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


def _token(
    *,
    purpose: str,
    secret: str,
    nonce: str = "n1",
) -> str:
    return create_snack_inventory_form_token(
        SnackInventoryFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECHNICIAN_ID,
            machine_code=_MACHINE,
            fingerprint_id="fp-1",
            cell_keys=(_CELL,),
            product_codes=("SKU1",),
            issued_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        secret,
    )


def _deps(
    *,
    accept: _RecordingAccept | None = None,
) -> tuple[GoogleFormsWebhookDeps, _RecordingAccept, _RecordingDirectChat]:
    recording_accept = accept or _RecordingAccept()
    direct_chat = _RecordingDirectChat()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = _active_technician()
    deps = GoogleFormsWebhookDeps(
        accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
        accept_technician_warehouse_inventory=_UnusedAcceptWarehouse(),  # type: ignore[arg-type]
        accept_inventory_form_submission=_UnusedAcceptInventory(),  # type: ignore[arg-type]
        form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
        direct_warehouse_chat_notifier=direct_chat,
        telegram_user_resolver=resolver,
        bot=WebhookPlaceholderBot(),
        token_field_name=_TOKEN_FIELD,
        webhook_secret=_WEBHOOK_SECRET,
        webhook_signature_max_age_seconds=300,
        revision_form_token_secret="revision-secret",
        inventory_form_token_secret="inventory-secret",
        technician_warehouse_inventory_form_token_secret="warehouse-secret",
        verify_revision_form_token=verify_revision_form_token,
        verify_inventory_form_token=verify_inventory_form_token,
        verify_technician_warehouse_inventory_token=verify_technician_warehouse_inventory_token,
        peek_form_token=peek_form_token,
        accept_snack_inventory=recording_accept,
        snack_inventory_now_form_token_secret=_NOW_SECRET,
        snack_inventory_as_of_form_token_secret=_AS_OF_SECRET,
        verify_snack_inventory_form_token=verify_snack_inventory_form_token,
    )
    return deps, recording_accept, direct_chat


def test_snack_inventory_now_submitted_accepted() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "10"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "snack_inventory_now"
    assert body["machine_code"] == _MACHINE
    assert accept.calls == 1
    assert accept.last_kwargs["mode"] == "now"
    assert accept.last_kwargs["as_of"] is None
    assert accept.last_kwargs["quantities"] == {_CELL: Decimal("10")}
    assert direct_chat.calls == 0


def test_snack_inventory_as_of_submitted_accepted() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_as_of", secret=_AS_OF_SECRET)
    as_of = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)

    response = post_signed_webhook(
        client,
        _AS_OF_WEBHOOK,
        payload={
            "form_id": "form-snack-as-of",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "as_of", "value": as_of.isoformat()},
                {"title": "SnackA / 1", "value": "7"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "snack_inventory_as_of"
    assert body["machine_code"] == _MACHINE
    assert accept.calls == 1
    assert accept.last_kwargs["mode"] == "as_of"
    assert accept.last_kwargs["as_of"] == as_of
    assert accept.last_kwargs["quantities"] == {_CELL: Decimal("7")}
    assert direct_chat.calls == 0


def test_snack_inventory_bad_qty_returns_422_and_notifies() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "-1"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert "negative" in response.json()["detail"].lower()
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_snack_inventory_qty_at_max_accepted() -> None:
    """happy: qty == inventory_form_qty_max accepted."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET)
    qty_max = deps.inventory_form_qty_max

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": str(qty_max)},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {_CELL: Decimal(qty_max)}
    assert direct_chat.calls == 0


def test_snack_inventory_qty_above_max_422() -> None:
    """edge: qty = max+1 → 422."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET)
    qty_max = deps.inventory_form_qty_max

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": str(qty_max + 1)},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert str(qty_max) in response.json()["detail"]
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_snack_inventory_qty_strips_letters() -> None:
    """happy: ``15с`` accepted as 15 (letters ignored)."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "15с"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {_CELL: Decimal("15")}
    assert direct_chat.calls == 0


def test_snack_inventory_invalid_qty_string_returns_422_and_notifies() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_now", secret=_NOW_SECRET, nonce="n-bad-qty")

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "x"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert "invalid" in response.json()["detail"].lower()
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_snack_inventory_as_of_future_returns_422() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="snack_inventory_as_of", secret=_AS_OF_SECRET)
    future = datetime(2026, 7, 3, 0, 0, tzinfo=UTC)

    response = post_signed_webhook(
        client,
        _AS_OF_WEBHOOK,
        payload={
            "form_id": "form-snack-as-of",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "as_of", "value": future.isoformat()},
                {"title": "SnackA / 1", "value": "10"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert "future" in response.json()["detail"]
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_snack_inventory_token_cell_machine_mismatch_422() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    # Forge signed payload: create() rejects mismatch; verify must still reject.
    body = {
        "v": 1,
        "purpose": "snack_inventory_now",
        "technician_id": _TECHNICIAN_ID.value,
        "machine_code": _MACHINE,
        "fingerprint_id": "fp-1",
        "cell_keys": [["999", "SnackA", 1]],
        "product_codes": ["SKU1"],
        "issued_at": datetime(2026, 7, 2, 10, 0, tzinfo=UTC).isoformat(),
        "nonce": "n-mismatch",
    }
    encoded_body = _base64_urlsafe_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    token = f"{encoded_body}.{_sign(encoded_body, _NOW_SECRET)}"

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "10"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert "machine" in response.json()["detail"].lower()
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_snack_inventory_wrong_purpose_on_now_endpoint_422() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    # as_of purpose signed with now secret → peek purpose mismatch on now endpoint
    token = _token(purpose="snack_inventory_as_of", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-snack-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "SnackA / 1", "value": "10"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert accept.calls == 0
    assert direct_chat.calls == 1
