from __future__ import annotations

from dataclasses import replace

import pytest
from tests.application.close_period_helpers import (
    FakePeriodPartyNamesLookup,
    build_close_period_service,
    second_revision_event,
)

from src.application.inventory_reconciliation.period_errors import PeriodSnapshotNotReadyError
from src.domain.ids import TechnicianId


def test_close_period_persists_stripped_party_names() -> None:
    service, repo = build_close_period_service(
        party_names=FakePeriodPartyNamesLookup(location="  Loc  ", technician="  Tech  "),
    )

    result = service.execute(closing_event=second_revision_event())

    assert result is not None
    assert result.location_name == "Loc"
    assert result.technician_name == "Tech"
    assert result.responsible_technician_id == TechnicianId("tech-a")
    saved = repo.get_by_period_id("rev-1:rev-2")
    assert saved is not None
    assert saved.location_name == "Loc"
    assert saved.technician_name == "Tech"


def test_close_period_missing_location_name_raises_not_ready() -> None:
    service, repo = build_close_period_service(
        party_names=FakePeriodPartyNamesLookup(location=None, technician="Tech"),
    )

    with pytest.raises(PeriodSnapshotNotReadyError, match="location_name"):
        service.execute(closing_event=second_revision_event())

    assert repo.get_by_period_id("rev-1:rev-2") is None


def test_close_period_missing_technician_name_raises_not_ready() -> None:
    service, repo = build_close_period_service(
        party_names=FakePeriodPartyNamesLookup(location="Loc", technician=None),
    )

    with pytest.raises(PeriodSnapshotNotReadyError, match="technician_name"):
        service.execute(closing_event=second_revision_event())

    assert repo.get_by_period_id("rev-1:rev-2") is None


def test_close_overwrite_preserves_existing_party_names() -> None:
    service, repo = build_close_period_service(
        party_names=FakePeriodPartyNamesLookup(location="NEW", technician="NEW T"),
    )
    first = service.execute(closing_event=second_revision_event())
    assert first is not None
    repo.save(
        replace(
            first,
            location_name="OLD",
            technician_name="OLD T",
            status="pending_sales",
            ledger_posted=False,
            reconciled=False,
        ),
    )

    saved = service.execute(closing_event=second_revision_event())
    assert saved is not None
    assert saved.location_name == "OLD"
    assert saved.technician_name == "OLD T"
