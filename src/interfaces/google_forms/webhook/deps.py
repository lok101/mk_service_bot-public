from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import (
    AcceptInventoryFormSubmission,
    AcceptRevisionFormSubmission,
)
from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow import FormWorkflowNotifierRef
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    MicromarketInventoryFormTokenPayload,
    PeekedFormToken,
    RevisionFormTokenPayload,
    SnackInventoryFormTokenPayload,
    TechnicianWarehouseInventoryTokenPayload,
    VerifiedInventoryFormToken,
)
from src.domain.ids import TechnicianId
from src.domain.snack_loading.events import CellKey
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted

VerifyRevisionFormToken = Callable[[str, str], RevisionFormTokenPayload]
VerifyInventoryFormToken = Callable[[str, str], VerifiedInventoryFormToken]
VerifyTechnicianWarehouseInventoryToken = Callable[
    [str, str],
    TechnicianWarehouseInventoryTokenPayload,
]
VerifySnackInventoryFormToken = Callable[..., SnackInventoryFormTokenPayload]
VerifyMicromarketInventoryFormToken = Callable[..., MicromarketInventoryFormTokenPayload]
PeekFormToken = Callable[[str, str], PeekedFormToken | None]
SnackInventoryMode = Literal["now", "as_of"]
MicromarketInventoryMode = Literal["now", "as_of"]


@runtime_checkable
class AcceptTechnicianWarehouseInventory(Protocol):
    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted: ...


@runtime_checkable
class AcceptSnackInventoryWebhook(Protocol):
    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: SnackInventoryMode,
        as_of: datetime | None,
        submitted_at: datetime,
        quantities: Mapping[CellKey, Decimal],
        product_by_key: Mapping[CellKey, str],
        inventory_id: str,
    ) -> None: ...


@runtime_checkable
class AcceptMicromarketInventoryWebhook(Protocol):
    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: MicromarketInventoryMode,
        submitted_at: datetime,
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        as_of_from_form: datetime | None,
        partial: bool = True,
    ) -> None: ...


@runtime_checkable
class DirectWarehouseChatNotifier(Protocol):
    @beartype
    async def notify(
        self,
        *,
        technician_id: TechnicianId,
        reason: str,
    ) -> None: ...


@runtime_checkable
class WebhookTelegramBot(Protocol):
    @beartype
    async def send_message(self, **kwargs: object) -> None: ...


@runtime_checkable
class ReadinessProbe(Protocol):
    def mongo_ok(self) -> bool: ...

    def redis_ok(self) -> bool: ...

    def outbox_failed_count(self) -> int: ...

    def reference_data_freshness(self) -> dict[str, dict[str, object]]: ...


@beartype
@dataclass(frozen=True, slots=True)
class GoogleFormsWebhookDeps:
    accept_revision_form_submission: AcceptRevisionFormSubmission
    accept_technician_warehouse_inventory: AcceptTechnicianWarehouseInventory
    accept_inventory_form_submission: AcceptInventoryFormSubmission
    form_workflow_notifier: FormWorkflowNotifierRef
    direct_warehouse_chat_notifier: DirectWarehouseChatNotifier
    telegram_user_resolver: TelegramUserResolver
    bot: WebhookTelegramBot
    token_field_name: str
    webhook_secret: str
    webhook_signature_max_age_seconds: int
    revision_form_token_secret: str
    inventory_form_token_secret: str
    technician_warehouse_inventory_form_token_secret: str
    verify_revision_form_token: VerifyRevisionFormToken
    verify_inventory_form_token: VerifyInventoryFormToken
    verify_technician_warehouse_inventory_token: VerifyTechnicianWarehouseInventoryToken
    peek_form_token: PeekFormToken
    webhook_max_body_bytes: int = 3_000_000
    accept_snack_inventory: AcceptSnackInventoryWebhook | None = None
    snack_inventory_now_form_token_secret: str = ""
    snack_inventory_as_of_form_token_secret: str = ""
    verify_snack_inventory_form_token: VerifySnackInventoryFormToken | None = None
    accept_micromarket_inventory: AcceptMicromarketInventoryWebhook | None = None
    micromarket_inventory_now_form_token_secret: str = ""
    micromarket_inventory_as_of_form_token_secret: str = ""
    verify_micromarket_inventory_form_token: VerifyMicromarketInventoryFormToken | None = None
    inventory_form_qty_max: int = 99

    def __post_init__(self) -> None:
        if not self.webhook_secret:
            raise ValueError("Google Forms webhook secret must not be empty")
        if self.webhook_signature_max_age_seconds <= 0:
            raise ValueError("webhook_signature_max_age_seconds must be positive")
        if not self.revision_form_token_secret:
            raise ValueError("Google Forms revision token secret must not be empty")
        if not self.inventory_form_token_secret:
            raise ValueError("Google Forms inventory token secret must not be empty")
        if not self.technician_warehouse_inventory_form_token_secret:
            raise ValueError(
                "Google Forms technician warehouse inventory token secret must not be empty"
            )
        if not self.token_field_name.strip():
            raise ValueError("Google Forms token field name must not be empty")
        if self.webhook_max_body_bytes <= 0:
            raise ValueError("webhook_max_body_bytes must be positive")
