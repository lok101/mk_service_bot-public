from __future__ import annotations

from src.application.matrix_automation import PriceSnapshotDocument
from src.application.matrix_automation.models import SnapshotLineRecord
from src.infrastructure.matrix_automation.memory_snapshots import InMemoryMatrixPriceSnapshotStore
from src.infrastructure.matrix_automation.mongo_snapshots import MongoMatrixPriceSnapshotStore


class _Collection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def insert_one(self, document: dict[str, object]) -> None:
        self.documents.append(document)

    def find(self, filter: dict[str, object], *, sort: list[tuple[str, int]] | None = None):
        machine_code = filter["machine_code"]
        logical_matrix_name = filter["logical_matrix_name"]
        matched = [
            doc
            for doc in self.documents
            if doc["machine_code"] == machine_code
            and doc["logical_matrix_name"] == logical_matrix_name
        ]
        if sort == [("recorded_at", -1)]:
            matched.sort(key=lambda doc: str(doc["recorded_at"]), reverse=True)
        return iter(matched)


def _document(*, recorded_at: str) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at=recorded_at,
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="MS-1",
                product_name="Кола 0.5",
                capacity=12,
                purchase_price="10.00",
                calculated_price="30.00",
                deploy_price="30.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


def test_mongo_store_get_latest_line_by_key() -> None:
    collection = _Collection()
    store = MongoMatrixPriceSnapshotStore(_collection=collection)
    store.save(_document(recorded_at="2026-07-08T10:00:00Z"))
    store.save(_document(recorded_at="2026-07-08T11:00:00Z"))
    latest = store.get_latest_line(
        machine_code="512",
        logical_matrix_name="Snacks",
        line_number=1,
    )
    assert latest is not None
    assert latest.recorded_at == "2026-07-08T11:00:00Z"
    assert latest.lines[0].product_name == "Кола 0.5"


def test_memory_store_roundtrip_product_name() -> None:
    store = InMemoryMatrixPriceSnapshotStore()
    store.save(_document(recorded_at="2026-07-08T10:00:00Z"))
    latest = store.get_latest_line(
        machine_code="512",
        logical_matrix_name="Snacks",
        line_number=1,
    )
    assert latest is not None
    assert latest.lines[0].product_name == "Кола 0.5"


def test_memory_store_get_latest_line_falls_back_to_older_partial_doc() -> None:
    store = InMemoryMatrixPriceSnapshotStore()
    store.save(
        PriceSnapshotDocument(
            job_id="job-1",
            machine_code="512",
            logical_matrix_name="Snacks",
            recorded_at="2026-07-08T11:00:00Z",
            lines=(
                SnapshotLineRecord(
                    line_number=1,
                    product_code="MS-1",
                    product_name="Кола 0.5",
                    capacity=12,
                    purchase_price="10.00",
                    calculated_price="30.00",
                    deploy_price="30.00",
                    outcome="applied",
                    reason=None,
                    strong_price_increase=False,
                ),
            ),
        ),
    )
    store.save(
        PriceSnapshotDocument(
            job_id="job-0",
            machine_code="512",
            logical_matrix_name="Snacks",
            recorded_at="2026-07-08T10:00:00Z",
            lines=(
                SnapshotLineRecord(
                    line_number=3,
                    product_code="MS-3",
                    product_name="Chips",
                    capacity=8,
                    purchase_price="10.00",
                    calculated_price="30.00",
                    deploy_price="30.00",
                    outcome="applied",
                    reason=None,
                    strong_price_increase=False,
                ),
            ),
        ),
    )
    latest = store.get_latest_line(
        machine_code="512",
        logical_matrix_name="Snacks",
        line_number=3,
    )
    assert latest is not None
    assert latest.recorded_at == "2026-07-08T10:00:00Z"
    assert latest.lines[0].line_number == 3
