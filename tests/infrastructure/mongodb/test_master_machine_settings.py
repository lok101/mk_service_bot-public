from __future__ import annotations

import pytest

from src.application.master_data import (
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.domain.ids import MachineId
from src.infrastructure.mongodb.master_data import (
    _machine_from_document,
    _machine_to_document,
)


def test_machine_from_document_missing_settings_defaults_true() -> None:
    machine = _machine_from_document(
        {
            "_id": "101",
            "kind": "coffee",
            "status": "active_on_site",
            "label": None,
        }
    )
    assert machine.include_in_no_sales_monitoring is True
    assert machine.create_visit_on_no_sales is True


def test_machine_mongo_settings_roundtrip() -> None:
    original = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.IN_STORAGE,
        label="x",
        include_in_no_sales_monitoring=False,
        create_visit_on_no_sales=False,
    )
    restored = _machine_from_document(_machine_to_document(original))
    assert restored == original


def test_machine_document_missing_review_flag_is_included() -> None:
    machine = _machine_from_document(
        {
            "_id": "101",
            "kind": "coffee",
            "status": "active_on_site",
            "label": None,
        }
    )
    assert machine.include_in_visit_photo_review is True


def test_machine_document_review_flag_roundtrip() -> None:
    original = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.IN_STORAGE,
        label="x",
        include_in_no_sales_monitoring=False,
        create_visit_on_no_sales=False,
        include_in_visit_photo_review=False,
    )
    restored = _machine_from_document(_machine_to_document(original))
    assert restored.include_in_visit_photo_review is False
    assert restored == original


def test_machine_document_review_flag_must_be_bool() -> None:
    with pytest.raises(ValueError, match="include_in_visit_photo_review"):
        _machine_from_document(
            {
                "_id": "101",
                "kind": "coffee",
                "status": "active_on_site",
                "label": None,
                "include_in_visit_photo_review": "yes",
            }
        )
