from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pymongo.database import Database
from tests.integration.stack import (
    FORM_TOKEN_FIELD_NAME,
    FORM_TOKEN_SECRET,
    INVENTORY_FORM_TOKEN_SECRET,
    WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET,
    WEBHOOK_SECRET,
    WebhookPipelineStack,
)
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.outbox.handler_ids import PERIOD_RECONCILIATION_HANDLER_ID
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ExternalWarehouseMoveLine,
)
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    RevisionFormTokenPayload,
    TechnicianWarehouseInventoryTokenPayload,
    create_loading_form_token,
    create_revision_form_token,
    create_technician_warehouse_inventory_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.machine_sales import MachineSale
from src.domain.technician_settlement import (
    PeriodAccountabilityRecorded,
    TechnicianReconciliationSessionCommitted,
)
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PENDING, OUTBOX_STATUS_PROCESSED
from src.infrastructure.outbox.serialization import event_from_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.testing import TEST_TECHNICIAN_ID

BUNDLE_CODE = "2301"
COMPONENT_CODE = "coffee-1"
DEFAULT_MACHINE_ID = MachineId("vm-settlement-e2e")
REV1_AT = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
DEFAULT_SUPPLY_MOVE_AT = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


def external_supply_move(
    *,
    document_id: str,
    source_store: str,
    target_store: str,
    sku_code: str,
    quantity: Decimal,
    moment: datetime = DEFAULT_SUPPLY_MOVE_AT,
) -> ExternalWarehouseMove:
    return ExternalWarehouseMove(
        document_id=document_id,
        source_store_code=source_store,
        target_store_code=target_store,
        moment=moment,
        updated_at=moment,
        lines=(
            ExternalWarehouseMoveLine(
                product_code=sku_code,
                product_name=sku_code,
                quantity=quantity,
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class SettlementPeriodFixture:
    rev1_completed_at: datetime
    loading_at: datetime
    rev2_at: datetime
    sale_at: datetime


@dataclass(frozen=True, slots=True)
class ClosingRevisionResult:
    event_id: str
    period_id: str
    timeline: SettlementPeriodFixture


def default_latte_recipe() -> CoffeeRecipe:
    return CoffeeRecipe(
        drink_product_id="drink-latte",
        name="Test drink",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-coffee",
                quantity_per_unit=Decimal("30"),
            ),
        ),
    )


def seed_latte_bom(stack: WebhookPipelineStack) -> None:
    from src.application.product_identity.models import DomainProduct

    if stack.domain_product_store.get("drink-latte") is None:
        stack.domain_product_store.insert(
            DomainProduct(
                domain_product_id="drink-latte",
                number="D-LATTE",
                name="Test drink",
                catalog_code=None,
                hidden=False,
                kind="coffee_drink",
                legacy_ms_code=BUNDLE_CODE,
            ),
        )
    if stack.domain_product_store.get("ing-coffee") is None:
        stack.domain_product_store.insert(
            DomainProduct(
                domain_product_id="ing-coffee",
                number="I-COFFEE",
                name="Coffee",
                catalog_code=COMPONENT_CODE,
                hidden=False,
                kind="coffee_ingredient",
            ),
        )
    stack.coffee_recipe_repo.upsert(default_latte_recipe())


def _revision_token(*, machine_id: MachineId, nonce: str) -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            issued_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        FORM_TOKEN_SECRET,
    )


def _loading_token(*, machine_id: MachineId, nonce: str) -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            issued_at=datetime(2026, 6, 5, 9, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        INVENTORY_FORM_TOKEN_SECRET,
    )


def _revision_answers(token: str, *, coffee: str) -> list[dict[str, str]]:
    return [
        {"title": FORM_TOKEN_FIELD_NAME, "value": token},
        {"title": "Кофе", "value": coffee},
    ]


def _loading_answers(token: str, *, coffee: str = "1") -> list[dict[str, str]]:
    return [
        {"title": FORM_TOKEN_FIELD_NAME, "value": token},
        {"title": "Кофе", "value": coffee},
    ]


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def drain_outbox(worker: OutboxWorker) -> int:
    total = 0
    while True:
        processed = await worker.process_batch()
        if processed == 0:
            return total
        total += processed


def drain_outbox_sync(stack: WebhookPipelineStack) -> int:
    return asyncio.run(drain_outbox(stack.outbox_worker))


async def _drain_handler(stack: WebhookPipelineStack, handler_id: str) -> int:
    collection = stack.outbox_store._collection
    total = 0
    while True:
        document = collection.find_one(
            {"status": OUTBOX_STATUS_PENDING, "handler_id": handler_id},
        )
        if document is None:
            return total
        entry_id = str(document["entry_id"])
        claim_id = str(uuid.uuid4())
        claimed = collection.find_one_and_update(
            {"entry_id": entry_id, "status": OUTBOX_STATUS_PENDING},
            {
                "$set": {
                    "status": "processing",
                    "claim_id": claim_id,
                    "claimed_at": datetime.now(tz=UTC),
                },
            },
        )
        if claimed is None:
            continue
        event = event_from_outbox_document(claimed["event_document"])
        await stack.outbox_worker.processors.process(handler_id, event)
        stack.outbox_store.mark_processed(entry_id, claim_id=claim_id)
        total += 1


def drain_handler_sync(stack: WebhookPipelineStack, handler_id: str) -> int:
    return asyncio.run(_drain_handler(stack, handler_id))


def post_warehouse_inventory(
    stack: WebhookPipelineStack,
    *,
    technician_id: TechnicianId | str,
    coffee: str,
    nonce: str,
    submitted_at: datetime,
) -> object:
    resolved_technician = (
        technician_id if isinstance(technician_id, TechnicianId) else TechnicianId(technician_id)
    )
    token = create_technician_warehouse_inventory_token(
        TechnicianWarehouseInventoryTokenPayload(
            technician_id=resolved_technician,
            issued_at=submitted_at - timedelta(hours=1),
            nonce=nonce,
        ),
        WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET,
    )
    return post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/technician-warehouse-inventory-submitted",
        payload={
            "form_id": f"form-warehouse-{nonce}",
            "submitted_at": _iso_z(submitted_at),
            "token": token,
            "answers": [
                {"title": FORM_TOKEN_FIELD_NAME, "value": token},
                {"title": "Кофе", "value": coffee},
            ],
        },
        secret=WEBHOOK_SECRET,
    )


def post_warehouse_loading(
    stack: WebhookPipelineStack,
    *,
    technician_id: TechnicianId | str,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
    loading_coffee: str,
    nonce: str,
    submitted_at: datetime,
) -> None:
    resolved_technician = (
        technician_id if isinstance(technician_id, TechnicianId) else TechnicianId(technician_id)
    )
    token = create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=resolved_technician,
            machine_id=machine_id,
            issued_at=submitted_at - timedelta(hours=1),
            nonce=nonce,
        ),
        INVENTORY_FORM_TOKEN_SECRET,
    )
    response = post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/loading-submitted",
        payload={
            "form_id": f"form-{nonce}",
            "submitted_at": _iso_z(submitted_at),
            "token": token,
            "answers": _loading_answers(token, coffee=loading_coffee),
        },
        secret=WEBHOOK_SECRET,
    )
    assert response.status_code == 200


def post_opening_revision(
    stack: WebhookPipelineStack,
    *,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
    opening_coffee: str = "100",
    nonce: str = "settlement-rev-1",
) -> SettlementPeriodFixture:
    token = _revision_token(machine_id=machine_id, nonce=nonce)
    response = post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": f"form-{nonce}",
            "submitted_at": _iso_z(REV1_AT),
            "revision_token": token,
            "answers": _revision_answers(token, coffee=opening_coffee),
        },
        secret=WEBHOOK_SECRET,
    )
    assert response.status_code == 200

    rev1_events = stack.event_store.get_events_for_machine(machine_id)
    assert len(rev1_events) == 1
    rev1_event = rev1_events[0]
    assert isinstance(rev1_event, RevisionCompleted)
    assert rev1_event.responsibility_expires_at is not None
    rev2_at = (rev1_event.responsibility_expires_at - timedelta(days=1)).astimezone(UTC)
    loading_at = rev1_event.completed_at + timedelta(days=1)
    assert loading_at < rev2_at
    return SettlementPeriodFixture(
        rev1_completed_at=rev1_event.completed_at,
        loading_at=loading_at,
        rev2_at=rev2_at,
        sale_at=rev2_at,
    )


def post_loading(
    stack: WebhookPipelineStack,
    timeline: SettlementPeriodFixture,
    *,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
    nonce: str = "settlement-load-1",
    loading_coffee: str = "1",
) -> None:
    token = _loading_token(machine_id=machine_id, nonce=nonce)
    response = post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/loading-submitted",
        payload={
            "form_id": f"form-{nonce}",
            "submitted_at": _iso_z(timeline.loading_at),
            "token": token,
            "answers": _loading_answers(token, coffee=loading_coffee),
        },
        secret=WEBHOOK_SECRET,
    )
    assert response.status_code == 200


def insert_bundle_sale(
    stack: WebhookPipelineStack,
    timeline: SettlementPeriodFixture,
    *,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
    source_id: str,
    occurred_at: datetime | None = None,
    ingested_at: datetime | None = None,
) -> None:
    at = occurred_at if occurred_at is not None else timeline.sale_at
    ingested = ingested_at if ingested_at is not None else timeline.rev2_at
    stack.machine_sales_store.insert_if_absent(
        MachineSale(
            source_id=source_id,
            machine_id=machine_id,
            product_code=BUNDLE_CODE,
            quantity=Decimal("1"),
            occurred_at=at,
            ingested_at=ingested,
            sale_kind="coffee",
        ),
    )


def post_closing_revision(
    stack: WebhookPipelineStack,
    timeline: SettlementPeriodFixture,
    *,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
    closing_coffee: str,
    nonce: str = "settlement-rev-2",
) -> ClosingRevisionResult:
    token = _revision_token(machine_id=machine_id, nonce=nonce)
    response = post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": f"form-{nonce}",
            "submitted_at": _iso_z(timeline.rev2_at),
            "revision_token": token,
            "answers": _revision_answers(token, coffee=closing_coffee),
        },
        secret=WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    event_id = response.json()["event_id"]
    period_id = resolve_period_id(stack, machine_id=machine_id)
    return ClosingRevisionResult(
        event_id=event_id,
        period_id=period_id,
        timeline=timeline,
    )


def resolve_period_id(
    stack: WebhookPipelineStack,
    *,
    machine_id: MachineId = DEFAULT_MACHINE_ID,
) -> str:
    revisions = [
        event
        for event in stack.event_store.get_events_for_machine(machine_id)
        if isinstance(event, RevisionCompleted)
    ]
    assert len(revisions) == 2
    return f"{revisions[0].revision_id.value}:{revisions[1].revision_id.value}"


def assert_snapshot(
    stack: WebhookPipelineStack,
    period_id: str,
    *,
    status: str,
    ledger_posted: bool,
    reconciled: bool = False,
    delta: Decimal | None = None,
) -> None:
    snapshot = stack.reconciliation_repo.get_by_period_id(period_id)
    assert snapshot is not None
    assert snapshot.status == status
    assert snapshot.ledger_posted is ledger_posted
    assert snapshot.reconciled is reconciled
    if delta is not None:
        assert len(snapshot.lines) == 1
        assert snapshot.lines[0].delta == delta


def assert_reconciliation_outbox_processed(
    mongo_database: Database,
    rev2_event_id: str,
) -> None:
    entry = mongo_database["domain_event_outbox"].find_one(
        {
            "event_id": rev2_event_id,
            "handler_id": PERIOD_RECONCILIATION_HANDLER_ID,
        },
    )
    assert entry is not None
    assert entry["status"] == OUTBOX_STATUS_PROCESSED


def assert_period_accountability_recorded(
    stack: WebhookPipelineStack,
    *,
    period_id: str,
) -> PeriodAccountabilityRecorded:
    events = stack.settlement_event_store.get_events_for_technician(
        TechnicianId(TEST_TECHNICIAN_ID.value),
    )
    matching = [
        event
        for event in events
        if isinstance(event, PeriodAccountabilityRecorded) and event.period_id == period_id
    ]
    assert len(matching) == 1
    return matching[0]


def assert_settlement_balance(
    stack: WebhookPipelineStack,
    *,
    product_code: str,
    expected: Decimal,
) -> None:
    aggregate = stack.settlement_repository.get(TechnicianId(TEST_TECHNICIAN_ID.value))
    balance = aggregate.net_balance_by_sku()
    assert balance.get(product_code, Decimal("0")) == expected


def assert_finalize_events(
    stack: WebhookPipelineStack,
) -> TechnicianReconciliationSessionCommitted:
    events = stack.settlement_event_store.get_events_for_technician(
        TechnicianId(TEST_TECHNICIAN_ID.value),
    )
    committed = [
        event for event in events if isinstance(event, TechnicianReconciliationSessionCommitted)
    ]
    legacy_completed = [
        event
        for event in events
        if event.__class__.__name__ == "TechnicianReconciliationSessionCompleted"
    ]
    legacy_cleared = [
        event
        for event in events
        if event.__class__.__name__ == "TechnicianLedgerClearedByReconciliation"
    ]
    assert len(committed) == 1
    assert legacy_completed == []
    assert legacy_cleared == []
    return committed[0]
