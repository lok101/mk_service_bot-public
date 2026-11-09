from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

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
from src.domain.form_tokens.codec import _create_machine_form_token
from src.domain.ids import MachineId, TechnicianId

_SECRET = "test-secret"
_INVENTORY_SECRET = "inventory-secret"
_NOW = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_TECHNICIAN_ID = TechnicianId("tech-1")


def _revision_payload() -> RevisionFormTokenPayload:
    return RevisionFormTokenPayload(
        technician_id=_TECHNICIAN_ID,
        machine_id=MachineId("vm-01"),
        issued_at=_NOW,
        nonce="revision-1",
    )


def _warehouse_payload() -> TechnicianWarehouseInventoryTokenPayload:
    return TechnicianWarehouseInventoryTokenPayload(
        technician_id=_TECHNICIAN_ID,
        issued_at=_NOW,
        nonce="warehouse-1",
    )


def _decode_payload_without_verifying(token: str) -> dict[str, object]:
    payload_b64, _ = token.split(".", maxsplit=1)
    padding = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + padding))


@pytest.fixture
def revision_payload() -> RevisionFormTokenPayload:
    return RevisionFormTokenPayload(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-01"),
        issued_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        nonce="nonce-revision",
    )


@pytest.fixture
def loading_payload() -> InventoryFormTokenPayload:
    return InventoryFormTokenPayload(
        technician_id=TechnicianId("tech-2"),
        machine_id=MachineId("vm-02"),
        issued_at=datetime(2026, 5, 15, 11, 0, tzinfo=UTC),
        nonce="nonce-loading",
    )


def test_revision_form_token_round_trip(
    revision_payload: RevisionFormTokenPayload,
) -> None:
    token = create_revision_form_token(revision_payload, _SECRET)
    verified = verify_revision_form_token(token, _SECRET)

    assert verified == revision_payload


def test_loading_form_token_round_trip(
    loading_payload: InventoryFormTokenPayload,
) -> None:
    token = create_loading_form_token(loading_payload, _INVENTORY_SECRET)
    verified = verify_inventory_form_token(token, _INVENTORY_SECRET)

    assert verified.purpose == "loading"
    assert verified.technician_id == loading_payload.technician_id
    assert verified.machine_id == loading_payload.machine_id
    assert verified.issued_at == loading_payload.issued_at
    assert verified.nonce == loading_payload.nonce


def test_verify_inventory_form_token_rejects_revision_token(
    revision_payload: RevisionFormTokenPayload,
) -> None:
    token = create_revision_form_token(revision_payload, _INVENTORY_SECRET)

    with pytest.raises(ValueError, match="purpose is invalid"):
        verify_inventory_form_token(token, _INVENTORY_SECRET)


def test_verify_inventory_form_token_rejects_residual_pre_loading_purpose(
    loading_payload: InventoryFormTokenPayload,
) -> None:
    token = _create_machine_form_token(
        technician_id=loading_payload.technician_id,
        machine_id=loading_payload.machine_id,
        issued_at=loading_payload.issued_at,
        nonce=loading_payload.nonce,
        purpose="pre_loading",
        secret=_INVENTORY_SECRET,
    )

    with pytest.raises(ValueError, match="purpose is invalid"):
        verify_inventory_form_token(token, _INVENTORY_SECRET)


def test_verify_revision_form_token_rejects_wrong_secret(
    revision_payload: RevisionFormTokenPayload,
) -> None:
    token = create_revision_form_token(revision_payload, _SECRET)

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_revision_form_token(token, "other-secret")


def test_verify_revision_form_token_rejects_expired_token() -> None:
    expired_payload = RevisionFormTokenPayload(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-01"),
        issued_at=datetime(2020, 1, 1, tzinfo=UTC),
        nonce="nonce-expired",
    )
    token = create_revision_form_token(expired_payload, _SECRET)

    with pytest.raises(ValueError, match="has expired"):
        verify_revision_form_token(token, _SECRET, max_age_hours=24.0)


def test_warehouse_inventory_token_round_trip_without_machine_id() -> None:
    payload = TechnicianWarehouseInventoryTokenPayload(
        technician_id=TechnicianId("tech-1"),
        issued_at=_NOW,
        nonce="warehouse-1",
    )
    token = create_technician_warehouse_inventory_token(payload, _SECRET)
    verified = verify_technician_warehouse_inventory_token(token, _SECRET)
    assert verified == payload
    body = _decode_payload_without_verifying(token)
    assert body["purpose"] == "technician_warehouse_inventory"
    assert "machine_id" not in body


def test_warehouse_verify_rejects_revision_token() -> None:
    token = create_revision_form_token(_revision_payload(), _SECRET)
    with pytest.raises(ValueError, match="purpose"):
        verify_technician_warehouse_inventory_token(token, _SECRET)


def test_revision_verify_rejects_warehouse_token() -> None:
    token = create_technician_warehouse_inventory_token(_warehouse_payload(), _SECRET)
    with pytest.raises(ValueError, match="purpose"):
        verify_revision_form_token(token, _SECRET)


def test_peek_returns_warehouse_technician_without_machine() -> None:
    token = create_technician_warehouse_inventory_token(_warehouse_payload(), _SECRET)
    peeked = peek_form_token(token, _SECRET)
    assert peeked is not None
    assert peeked.purpose == "technician_warehouse_inventory"
    assert peeked.technician_id == TechnicianId("tech-1")
    assert peeked.machine_id is None


def test_warehouse_verify_rejects_expired_token() -> None:
    expired_payload = TechnicianWarehouseInventoryTokenPayload(
        technician_id=_TECHNICIAN_ID,
        issued_at=_NOW - timedelta(hours=25),
        nonce="warehouse-expired",
    )
    token = create_technician_warehouse_inventory_token(expired_payload, _SECRET)
    with pytest.raises(ValueError, match="expired"):
        verify_technician_warehouse_inventory_token(token, _SECRET, max_age_hours=24.0)


def test_warehouse_verify_rejects_wrong_secret() -> None:
    token = create_technician_warehouse_inventory_token(_warehouse_payload(), _SECRET)
    with pytest.raises(ValueError, match="signature"):
        verify_technician_warehouse_inventory_token(token, "wrong-secret")
