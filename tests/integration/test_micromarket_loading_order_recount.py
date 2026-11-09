from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import create_autospec
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.micromarket_loading import AcceptMicromarketInventory
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
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketSalesAfter,
)
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
_TOKEN_FIELD = "Код заявки."
_TZ = ZoneInfo("Europe/Moscow")
_OPEN_AT = datetime(2026, 9, 3, 10, 0, tzinfo=_TZ)


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _UnusedAcceptRevision:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("revision accept must not be called")


class _UnusedAcceptInventory:
    def execute_loading(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("loading accept must not be called")


class _UnusedAcceptWarehouse:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("warehouse accept must not be called")


class _RecordingDirectChat:
    calls: int = 0

    async def notify(self, **kwargs: object) -> None:
        self.calls += 1


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


def _token(*, nonce: str) -> str:
    return create_micromarket_inventory_form_token(
        MicromarketInventoryFormTokenPayload(
            purpose="micromarket_inventory_now",
            technician_id=_TECHNICIAN_ID,
            machine_code=_MACHINE,
            fingerprint_id="fp-mm-1",
            product_codes=(_PRODUCT,),
            issued_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        _NOW_SECRET,
    )


def _seed_open_order(cycle_store: _MemoryCycleStore) -> None:
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE)
    cycle.open_order(
        order_id="order-701",
        move_id="move-701",
        lines=(
            DraftLine(
                product_code=_PRODUCT,
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=_OPEN_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    cycle_store.save(cycle)


def _seed_shelf(stock_store: InMemoryMicromarketDeviceStockStore) -> None:
    stock = MicromarketDeviceStock(machine_code=_MACHINE)
    stock.apply_inventory(
        as_of=_OPEN_AT,
        quantities={_PRODUCT: Decimal("1")},
        inventory_id="seed-shelf",
    )
    stock_store.save(stock)


def _deps(
    accept: AcceptMicromarketInventory,
) -> GoogleFormsWebhookDeps:
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = _active_technician()
    return GoogleFormsWebhookDeps(
        accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
        accept_technician_warehouse_inventory=_UnusedAcceptWarehouse(),  # type: ignore[arg-type]
        accept_inventory_form_submission=_UnusedAcceptInventory(),  # type: ignore[arg-type]
        form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
        direct_warehouse_chat_notifier=_RecordingDirectChat(),
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
        accept_micromarket_inventory=accept,
        micromarket_inventory_now_form_token_secret=_NOW_SECRET,
        micromarket_inventory_as_of_form_token_secret=_AS_OF_SECRET,
        verify_micromarket_inventory_form_token=verify_micromarket_inventory_form_token,
    )


def _post_now(client: TestClient, *, nonce: str, qty: str) -> object:
    token = _token(nonce=nonce)
    return post_signed_webhook(
        client,
        _NOW_WEBHOOK,
        payload={
            "form_id": "form-mm-now",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": [
                {"title": _TOKEN_FIELD, "value": token},
                {"title": _PRODUCT, "value": qty},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )


@pytest.mark.integration
def test_second_now_webhook_replaces() -> None:
    # happy: second now after recounted → 200, shelf=new qty, deltas from shelf_before
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    _seed_shelf(stock_store)
    _seed_open_order(cycle_store)
    accept = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        cycle_store=cycle_store,
    )
    client = TestClient(build_google_forms_webhook_app(_deps(accept)))

    first = _post_now(client, nonce="n1", qty="4")
    assert first.status_code == 200

    second = _post_now(client, nonce="n2", qty="9")
    assert second.status_code == 200

    cycle = cycle_store.load(_MACHINE)
    assert cycle is not None
    assert cycle.status is OrderStatus.RECOUNTED
    assert cycle.shelf_before == ((_PRODUCT, Decimal("1")),)
    # form 9 − (shelf_before 1 + launch 2) = 6
    assert cycle.deltas == ((_PRODUCT, Decimal("6")),)
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty(_PRODUCT) == Decimal("9")
