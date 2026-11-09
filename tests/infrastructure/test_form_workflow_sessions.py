from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.application.form_workflow.models import utc_now
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.form_workflow_sessions import MongoFormWorkflowSessionStore
from src.interfaces.telegram.form_workflow import FormWorkflowSession


@pytest.fixture
def mongo_store() -> MongoFormWorkflowSessionStore:
    client = mongomock.MongoClient()
    settings = MongoSettings(uri="mongodb://localhost:27017", database="test_db")
    collection = client[settings.database][settings.form_workflow_sessions_collection]
    return MongoFormWorkflowSessionStore.from_collection(collection, ttl_seconds=3600)


def _session(*, purpose: str = "loading") -> FormWorkflowSession:
    return FormWorkflowSession(
        chat_id=100,
        telegram_user_id=200,
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        machine_name="VM 1",
        purpose=purpose,  # type: ignore[arg-type]
        maintenance_screen="maintenance",
        registered_at=utc_now(),
    )


def test_upsert_and_find(mongo_store: MongoFormWorkflowSessionStore) -> None:
    session = _session()
    mongo_store.upsert(session)

    found = mongo_store.find(session.technician_id, session.machine_id, session.purpose)
    assert found is not None
    assert found.chat_id == 100
    assert found.machine_name == "VM 1"


def test_upsert_overwrites_same_key(mongo_store: MongoFormWorkflowSessionStore) -> None:
    session = _session()
    mongo_store.upsert(session)
    updated = FormWorkflowSession(
        chat_id=101,
        telegram_user_id=201,
        technician_id=session.technician_id,
        machine_id=session.machine_id,
        machine_name="Updated",
        purpose=session.purpose,
        maintenance_screen="admin_maintenance",
        registered_at=datetime.now(tz=UTC),
    )
    mongo_store.upsert(updated)

    found = mongo_store.find(session.technician_id, session.machine_id, session.purpose)
    assert found is not None
    assert found.chat_id == 101
    assert found.maintenance_screen == "admin_maintenance"


def test_remove_returns_session(mongo_store: MongoFormWorkflowSessionStore) -> None:
    session = _session(purpose="revision")
    mongo_store.upsert(session)

    removed = mongo_store.remove(session.technician_id, session.machine_id, session.purpose)
    assert removed is not None
    assert removed.purpose == "revision"
    assert mongo_store.find(session.technician_id, session.machine_id, session.purpose) is None
