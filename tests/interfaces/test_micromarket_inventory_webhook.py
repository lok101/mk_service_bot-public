from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import create_autospec

from fastapi.testclient import TestClient
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.micromarket_loading.accept_inventory import VisitFinalizedRecountRejected
from src.domain.form_tokens import (
    MicromarketInventoryFormTokenPayload,
    create_micromarket_inventory_form_token,
    peek_form_token,
    verify_inventory_form_token,
    verify_micromarket_inventory_form_token,
    verify_revision_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    WebhookPlaceholderBot,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier

_WEBHOOK_SECRET = "webhook-secret"
_NOW_SECRET = "mm-now-secret"
_AS_OF_SECRET = "mm-as-of-secret"
_TECHNICIAN_ID = TechnicianId("tech-mm")
_TELEGRAM_USER_ID = 616161
_MACHINE = "701"
_PRODUCT = "2311"
_SUBMITTED_AT = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
_NOW_WEBHOOK = "/webhooks/google-forms/micromarket-inventory-now-submitted"
_AS_OF_WEBHOOK = "/webhooks/google-forms/micromarket-inventory-as-of-submitted"
_TOKEN_FIELD = "Код заявки."


@dataclass
class _RecordingAccept:
    calls: int = 0
    last_kwargs: dict[str, object] = field(default_factory=dict)
    error: Exception | None = None

    def execute(self, **kwargs: object) -> None:
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        if self.error is not None:
            raise self.error


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
        user_id=SystemUserId("user-mm"),
        name="MM Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


def _token(*, purpose: str, secret: str, nonce: str = "n1") -> str:
    return create_micromarket_inventory_form_token(
        MicromarketInventoryFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECHNICIAN_ID,
            machine_code=_MACHINE,
            fingerprint_id="fp-mm-1",
            product_codes=(_PRODUCT,),
            issued_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
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
        accept_micromarket_inventory=recording_accept,
        micromarket_inventory_now_form_token_secret=_NOW_SECRET,
        micromarket_inventory_as_of_form_token_secret=_AS_OF_SECRET,
        verify_micromarket_inventory_form_token=verify_micromarket_inventory_form_token,
    )
    return deps, recording_accept, direct_chat


def test_micromarket_inventory_now_webhook_happy() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "4"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "micromarket_inventory_now"
    assert body["machine_code"] == _MACHINE
    assert accept.calls == 1
    assert accept.last_kwargs["mode"] == "now"
    assert accept.last_kwargs["as_of_from_form"] is None
    assert accept.last_kwargs["submitted_at"] == _SUBMITTED_AT
    assert accept.last_kwargs["quantities"] == {_PRODUCT: Decimal("4")}
    assert direct_chat.calls == 0


def test_micromarket_inventory_as_of_webhook_happy() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_as_of", secret=_AS_OF_SECRET)
    as_of = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

    response = post_signed_webhook(
        client,
        _AS_OF_WEBHOOK,
        payload={
            "form_id": "form-mm-as-of",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "as_of", "value": as_of.isoformat()},
                {"title": _PRODUCT, "value": "7"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "micromarket_inventory_as_of"
    assert accept.calls == 1
    assert accept.last_kwargs["mode"] == "as_of"
    assert accept.last_kwargs["as_of_from_form"] == as_of
    assert accept.last_kwargs["quantities"] == {_PRODUCT: Decimal("7")}
    assert direct_chat.calls == 0


def test_micromarket_inventory_webhook_bad_signature_401() -> None:
    deps, accept, _direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "4"},
            ],
        },
        secret="wrong-secret",
    )

    assert response.status_code == 401
    assert accept.calls == 0


def test_micromarket_inventory_webhook_bad_qty_422() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "-1"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert "negative" in response.json()["detail"].lower()
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_micromarket_inventory_webhook_qty_at_max_accepted() -> None:
    """happy: qty == inventory_form_qty_max accepted."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)
    qty_max = deps.inventory_form_qty_max

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": str(qty_max)},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {_PRODUCT: Decimal(qty_max)}
    assert direct_chat.calls == 0


def test_micromarket_inventory_webhook_qty_above_max_422() -> None:
    """edge: qty = max+1 → 422."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)
    qty_max = deps.inventory_form_qty_max

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": str(qty_max + 1)},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    assert str(qty_max) in response.json()["detail"]
    assert accept.calls == 0
    assert direct_chat.calls == 1


def test_micromarket_inventory_webhook_qty_strips_letters() -> None:
    """happy: ``15с`` accepted as 15 (letters ignored)."""
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)

    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "15с"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {_PRODUCT: Decimal("15")}
    assert direct_chat.calls == 0


def test_micromarket_inventory_webhook_zips_qty_by_token_order_not_title_sort() -> None:
    """regression: zip qty ↔ product_codes by token order (shelf flatten), not alpha titles."""
    deps, accept, _direct = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    # Non-alphabetical token order (as after shelf pages flatten).
    codes = ("d-9", "d-1", "d-2")
    token = create_micromarket_inventory_form_token(
        MicromarketInventoryFormTokenPayload(
            purpose="micromarket_inventory_now",
            technician_id=_TECHNICIAN_ID,
            machine_code=_MACHINE,
            fingerprint_id="fp-mm-zip-order",
            product_codes=codes,
            issued_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
            nonce="zip-order-1",
        ),
        _NOW_SECRET,
    )
    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-zip",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "Яблоко", "value": "9"},
                {"title": "Абрикос", "value": "1"},
                {"title": "Банан", "value": "2"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {
        "d-9": Decimal("9"),
        "d-1": Decimal("1"),
        "d-2": Decimal("2"),
    }


def test_micromarket_inventory_webhook_empty_qty_is_omit_not_422() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = create_micromarket_inventory_form_token(
        MicromarketInventoryFormTokenPayload(
            purpose="micromarket_inventory_now",
            technician_id=_TECHNICIAN_ID,
            machine_code=_MACHINE,
            fingerprint_id="fp-mm-omit",
            product_codes=("2311", "2312"),
            issued_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
            nonce="omit-1",
        ),
        _NOW_SECRET,
    )
    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-omit",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": "2311", "value": "4"},
                {"title": "2312", "value": ""},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {"2311": Decimal("4")}
    assert "2312" not in accept.last_kwargs["quantities"]
    assert direct_chat.calls == 0


def test_micromarket_inventory_webhook_whitespace_qty_is_omit() -> None:
    deps, accept, direct_chat = _deps()
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)
    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-ws",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "  "},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {}
    assert direct_chat.calls == 0


def test_micromarket_inventory_now_webhook_visit_finalized_returns_409() -> None:
    """error: VisitFinalizedRecountRejected → 409 (not generic ValueError→422)."""
    deps, accept, _direct_chat = _deps(
        accept=_RecordingAccept(error=VisitFinalizedRecountRejected("visit finalized")),
    )
    client = TestClient(build_google_forms_webhook_app(deps))
    token = _token(purpose="micromarket_inventory_now", secret=_NOW_SECRET)
    response = post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-final",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": "4"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 409
    assert accept.calls == 1
