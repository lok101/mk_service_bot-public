from __future__ import annotations

import mongomock
import pytest

from src.application.matrix_automation.job_models import (
    MatrixDeployJob,
    MatrixDeployJobUnit,
    ProductSwapBlockedLine,
    StrongPriceIncreaseLine,
)
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    BlockedProductRef,
    SkuStats,
)
from src.infrastructure.matrix_automation.mongo_jobs import MongoMatrixDeployJobRepository

_STARTED = "2026-07-10T00:00:00+00:00"
_FINISHED = "2026-07-10T00:05:00+00:00"


@pytest.fixture
def collection() -> mongomock.collection.Collection:
    return mongomock.MongoClient().db.matrix_deploy_jobs


def test_insert_creates_orphan_document_with_empty_audit_arrays(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    repository.insert(
        MatrixDeployJob.started(
            job_id="job-1",
            started_at=_STARTED,
            trigger="cron",
        ),
    )
    assert collection.find_one({"_id": "job-1"}) == {
        "_id": "job-1",
        "started_at": _STARTED,
        "finished_at": None,
        "status": None,
        "trigger": "cron",
        "units": [],
        "blocked_matrices": [],
    }


def test_insert_writes_seed_trigger(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    repository.insert(
        MatrixDeployJob.started(
            job_id="job-seed",
            started_at=_STARTED,
            trigger="seed",
        ),
    )
    doc = collection.find_one({"_id": "job-seed"})
    assert doc is not None
    assert doc["trigger"] == "seed"


def test_finalize_sets_all_terminal_fields_in_single_update(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(
        job_id="job-1",
        started_at=_STARTED,
        trigger="cron",
    )
    repository.insert(started)
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="applied",
        deploy_reason=None,
        sku_stats=SkuStats(applied=1),
        strong_price_increase_lines=(),
        product_swap_blocked_lines=(),
    )
    terminal = started.finalize(
        status="completed",
        finished_at=_FINISHED,
        units=(unit,),
        blocked_matrices=(),
        auto_sync_disabled_matrices=2,
    )

    repository.finalize(terminal)

    document = collection.find_one({"_id": "job-1"})
    assert document is not None
    assert document["trigger"] == "cron"
    assert document["started_at"] == _STARTED
    assert document["finished_at"] == _FINISHED
    assert document["status"] == "completed"
    assert document["auto_sync_disabled_matrices"] == 2
    assert document["blocked_matrices"] == []
    assert len(document["units"]) == 1
    assert document["units"][0]["logical_matrix_name"] == "Snacks"
    assert document["units"][0]["machine_code"] == "512"
    assert document["units"][0]["deploy_status"] == "applied"
    assert document["units"][0]["deploy_reason"] is None
    assert document["units"][0]["sku_stats"]["applied"] == 1


def test_mongo_persists_kit_machine_lookup_failed_reason(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(job_id="job-lookup", started_at=_STARTED)
    repository.insert(started)
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="failed",
        deploy_reason="kit_machine_lookup_failed",
        sku_stats=SkuStats(applied=0),
        strong_price_increase_lines=(),
        product_swap_blocked_lines=(),
    )
    terminal = started.finalize(
        status="failed",
        finished_at=_FINISHED,
        units=(unit,),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )
    repository.finalize(terminal)
    document = collection.find_one({"_id": "job-lookup"})
    assert document is not None
    assert document["units"][0]["deploy_reason"] == "kit_machine_lookup_failed"
    assert document["units"][0]["deploy_status"] == "failed"


def test_finalize_raises_when_job_is_not_orphan(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(job_id="job-1", started_at=_STARTED)
    repository.insert(started)
    terminal = started.finalize(
        status="completed",
        finished_at=_FINISHED,
        units=(),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )
    repository.finalize(terminal)
    with pytest.raises(RuntimeError, match="was not an orphan"):
        repository.finalize(terminal)


def test_blocked_skipped_unit_omits_optional_audit_fields_in_mongo(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(job_id="job-1", started_at=_STARTED)
    repository.insert(started)
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason="unknown_product_name",
        sku_stats=None,
        strong_price_increase_lines=(),
        product_swap_blocked_lines=(),
    )
    blocked = BlockedMatrixEntry(
        logical_matrix_name="Snacks",
        deploy_reason="unknown_product_name",
        detail="unknown_product_name: Cola",
        products=(BlockedProductRef(product_name="Cola", product_code=None),),
        machine_codes=("512",),
    )
    header_block = BlockedMatrixEntry(
        logical_matrix_name="Other",
        deploy_reason="invalid_matrix_header",
        detail="invalid_matrix_header: duplicate_machine_code: 100",
        products=(),
        machine_codes=("100",),
    )
    terminal = started.finalize(
        status="skipped",
        finished_at=_FINISHED,
        units=(unit,),
        blocked_matrices=(blocked, header_block),
        auto_sync_disabled_matrices=0,
    )

    repository.finalize(terminal)

    document = collection.find_one({"_id": "job-1"})
    assert document is not None
    unit_doc = document["units"][0]
    assert "sku_stats" not in unit_doc
    assert "strong_price_increase_lines" not in unit_doc
    assert "product_swap_blocked_lines" not in unit_doc
    assert document["blocked_matrices"][0]["products"] == [
        {"product_name": "Cola", "product_code": None},
    ]
    assert document["blocked_matrices"][1]["products"] == []


def test_incomplete_unit_persists_sku_stats_and_all_audit_lines(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(job_id="job-2", started_at=_STARTED)
    repository.insert(started)
    strong_lines = tuple(
        StrongPriceIncreaseLine(
            machine_code="512",
            line_number=index,
            product_code=f"P{index}",
            baseline="60.00",
            deploy_price="95.00",
            increase_pct="58.3",
        )
        for index in range(1, 13)
    )
    swap_lines = tuple(
        ProductSwapBlockedLine(
            machine_code="512",
            line_number=index,
            current_product="OLD",
            desired_product=None if index == 1 else "NEW",
            reason="stock_positive",
        )
        for index in range(1, 4)
    )
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason="incomplete_matrix_no_snapshot",
        sku_stats=SkuStats(
            skipped_no_baseline=1,
            strong_price_increase=12,
            product_swap_blocked=3,
        ),
        strong_price_increase_lines=strong_lines,
        product_swap_blocked_lines=swap_lines,
    )
    terminal = started.finalize(
        status="skipped",
        finished_at=_FINISHED,
        units=(unit,),
        blocked_matrices=(),
        auto_sync_disabled_matrices=1,
    )

    repository.finalize(terminal)

    document = collection.find_one({"_id": "job-2"})
    assert document is not None
    unit_doc = document["units"][0]
    assert unit_doc["sku_stats"] == {
        "applied": 0,
        "kept_previous": 0,
        "skipped_no_baseline": 1,
        "strong_price_increase": 12,
        "blocked_empty": 0,
        "product_swap_blocked": 3,
    }
    assert len(unit_doc["strong_price_increase_lines"]) == 12
    assert len(unit_doc["product_swap_blocked_lines"]) == 3
    assert unit_doc["product_swap_blocked_lines"][0]["desired_product"] is None


def test_applied_unit_serializes_decimal_values_as_exact_strings(collection) -> None:
    repository = MongoMatrixDeployJobRepository(collection)
    started = MatrixDeployJob.started(job_id="job-3", started_at=_STARTED)
    repository.insert(started)
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="applied",
        deploy_reason=None,
        sku_stats=SkuStats(applied=1, strong_price_increase=1),
        strong_price_increase_lines=(
            StrongPriceIncreaseLine(
                machine_code="512",
                line_number=5,
                product_code="ABC",
                baseline="60.00",
                deploy_price="95.00",
                increase_pct="58.3",
            ),
        ),
        product_swap_blocked_lines=(
            ProductSwapBlockedLine(
                machine_code="512",
                line_number=3,
                current_product="ABC",
                desired_product=None,
                reason="stock_positive",
            ),
        ),
    )
    terminal = started.finalize(
        status="completed",
        finished_at=_FINISHED,
        units=(unit,),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )

    repository.finalize(terminal)

    document = collection.find_one({"_id": "job-3"})
    assert document is not None
    strong = document["units"][0]["strong_price_increase_lines"][0]
    assert strong["baseline"] == "60.00"
    assert strong["deploy_price"] == "95.00"
    assert strong["increase_pct"] == "58.3"
    assert isinstance(strong["baseline"], str)
    assert isinstance(strong["deploy_price"], str)
    assert isinstance(strong["increase_pct"], str)
    swap = document["units"][0]["product_swap_blocked_lines"][0]
    assert "desired_product" in swap
    assert swap["desired_product"] is None
