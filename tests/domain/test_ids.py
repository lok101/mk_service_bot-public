from __future__ import annotations

import pytest

from src.domain.ids import (
    AccountabilityId,
    BatchId,
    EventId,
    FindingId,
    MachineId,
    ReconciliationSessionId,
    ResidualDocumentId,
    RevisionId,
    TechnicianId,
)

_ID_TYPES = (
    TechnicianId,
    MachineId,
    RevisionId,
    EventId,
    BatchId,
    FindingId,
    AccountabilityId,
    ReconciliationSessionId,
    ResidualDocumentId,
)


@pytest.mark.parametrize("id_type", _ID_TYPES)
def test_id_rejects_empty_string(id_type: type[object]) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        id_type("")


@pytest.mark.parametrize("id_type", _ID_TYPES)
def test_id_rejects_whitespace_only(id_type: type[object]) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        id_type("   ")


def test_accountability_id_rejects_blank() -> None:
    with pytest.raises(ValueError, match="AccountabilityId"):
        AccountabilityId("   ")


def test_reconciliation_session_id_keeps_value() -> None:
    assert ReconciliationSessionId("sess-1").value == "sess-1"


def test_residual_document_id_keeps_value() -> None:
    assert ResidualDocumentId("res-1").value == "res-1"
