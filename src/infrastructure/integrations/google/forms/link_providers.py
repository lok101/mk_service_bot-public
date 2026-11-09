from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.machine_operations.ports import (
    LoadingFormLinkProvider,
    RevisionFormLinkProvider,
    TechnicianWarehouseInventoryLinkProvider,
    WarehouseInventoryFormUnconfigured,
)
from src.domain.form_tokens import (
    LoadingFormTokenPayload,
    RevisionFormTokenPayload,
    TechnicianWarehouseInventoryTokenPayload,
    create_loading_form_token,
    create_revision_form_token,
    create_technician_warehouse_inventory_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import PrefilledFormLink
from src.infrastructure.integrations.google.forms.prefilled_urls import (
    create_prefilled_google_form_url,
)


@beartype
@dataclass(frozen=True, slots=True)
class PrefilledGoogleFormLinkProvider:
    form_url: str
    token_entry_id: str

    def __post_init__(self) -> None:
        if not self.form_url:
            raise ValueError("Google Form URL must not be empty")
        if not self.token_entry_id.startswith("entry."):
            raise ValueError("Google Form token entry id must start with 'entry.'")

    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        token: str,
    ) -> PrefilledFormLink:
        return PrefilledFormLink(
            url=create_prefilled_google_form_url(
                form_url=self.form_url,
                entry_id=self.token_entry_id,
                value=token,
            ),
        )


@beartype
@dataclass(frozen=True, slots=True)
class GoogleFormsRevisionFormLinkProvider(RevisionFormLinkProvider):
    form_url: str
    token_entry_id: str
    token_secret: str

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Google Form token secret must not be empty")
        PrefilledGoogleFormLinkProvider(
            form_url=self.form_url,
            token_entry_id=self.token_entry_id,
        )

    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        payload = RevisionFormTokenPayload(
            technician_id=technician_id,
            machine_id=machine_id,
            issued_at=datetime.now(tz=UTC),
            nonce=secrets.token_urlsafe(12),
        )
        token = create_revision_form_token(payload, self.token_secret)

        return PrefilledGoogleFormLinkProvider(
            form_url=self.form_url,
            token_entry_id=self.token_entry_id,
        ).create_link(
            technician_id=technician_id,
            machine_id=machine_id,
            token=token,
        )


@beartype
@dataclass(frozen=True, slots=True)
class GoogleFormsLoadingFormLinkProvider(LoadingFormLinkProvider):
    form_url: str
    token_entry_id: str
    token_secret: str

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Google Form token secret must not be empty")
        PrefilledGoogleFormLinkProvider(
            form_url=self.form_url,
            token_entry_id=self.token_entry_id,
        )

    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        payload = LoadingFormTokenPayload(
            technician_id=technician_id,
            machine_id=machine_id,
            issued_at=datetime.now(tz=UTC),
            nonce=secrets.token_urlsafe(12),
        )
        token = create_loading_form_token(payload, self.token_secret)

        return PrefilledGoogleFormLinkProvider(
            form_url=self.form_url,
            token_entry_id=self.token_entry_id,
        ).create_link(
            technician_id=technician_id,
            machine_id=machine_id,
            token=token,
        )


@beartype
@dataclass(frozen=True, slots=True)
class UnconfiguredTechnicianWarehouseInventoryLinkProvider(
    TechnicianWarehouseInventoryLinkProvider,
):
    @beartype
    def create_link(self, technician_id: TechnicianId) -> PrefilledFormLink:
        raise WarehouseInventoryFormUnconfigured(
            "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL is not configured",
        )


@beartype
@dataclass(frozen=True, slots=True)
class GoogleFormsTechnicianWarehouseInventoryLinkProvider(TechnicianWarehouseInventoryLinkProvider):
    form_url: str
    token_entry_id: str
    token_secret: str
    clock: Callable[[], datetime]

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Warehouse inventory form token secret must not be empty")
        PrefilledGoogleFormLinkProvider(
            form_url=self.form_url,
            token_entry_id=self.token_entry_id,
        )

    @beartype
    def create_link(self, technician_id: TechnicianId) -> PrefilledFormLink:
        payload = TechnicianWarehouseInventoryTokenPayload(
            technician_id=technician_id,
            issued_at=self.clock(),
            nonce=secrets.token_urlsafe(12),
        )
        token = create_technician_warehouse_inventory_token(payload, self.token_secret)
        return PrefilledFormLink(
            url=create_prefilled_google_form_url(
                form_url=self.form_url,
                entry_id=self.token_entry_id,
                value=token,
            ),
        )
