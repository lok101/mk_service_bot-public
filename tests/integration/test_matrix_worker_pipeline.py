from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from pymongo.database import Database
from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.daily_job import RunDailyMatrixDeployJob
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeployResult,
    MatrixParseState,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
    SnapshotLineRecord,
)
from src.application.matrix_automation.run_matrix_deploy_build import RunMatrixDeployBuild
from src.domain.matrix_pricing.formula import BaseMarginParams
from src.infrastructure.matrix_automation.mongo_jobs import MongoMatrixDeployJobRepository
from src.infrastructure.matrix_automation.mongo_snapshots import MongoMatrixPriceSnapshotStore
from src.infrastructure.matrix_automation.mongo_worker_status import (
    MongoMatrixWorkerStatusRepository,
)

pytestmark = pytest.mark.integration

_STARTED = "2026-07-10T00:00:00+00:00"
_FINISHED = "2026-07-10T00:01:00+00:00"
_JOB_ID = "integration-job-1"


class _Clock:
    def __init__(self, values: list[str]) -> None:
        self._values = list(values)

    def now_utc_iso(self) -> str:
        return self._values.pop(0)


class _Sync:
    def __init__(self, result: MatrixParseState) -> None:
        self._result = result

    def sync(self) -> MatrixParseState:
        return self._result


class _Build:
    def __init__(self, result: BuildMatrixDeployResult) -> None:
        self._result = result

    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult:
        return self._result


class _Deployer:
    def __init__(self, results: tuple[MatrixDeployResult, ...]) -> None:
        self._results = results
        self.calls: list[list[MatrixDeployPayload]] = []

    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]:
        self.calls.append(payloads)
        return list(self._results)


class _Notifier:
    def __init__(self) -> None:
        self.jobs: list[object] = []

    def notify(self, job: object, *, global_abort_reason: str | None = None) -> None:
        self.jobs.append(job)


class _Logger:
    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        return None


def _matrix(name: str, *machine_codes: str) -> EnabledLogicalMatrix:
    return EnabledLogicalMatrix(
        logical_matrix_name=name,
        machine_codes=machine_codes,
        matrix_multiplier=Decimal("1"),
        cells=(MatrixCatalogCell(1, "Cola", "A"),),
    )


def _state(*matrices: EnabledLogicalMatrix) -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=matrices,
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )


def _line() -> MatrixDeployPayloadLine:
    return MatrixDeployPayloadLine(
        line_number=1,
        product_code="A",
        product_name="Cola",
        deploy_price=Decimal("50.00"),
        capacity=10,
        outcome="applied",
        reason=None,
        strong_price_increase=False,
        purchase_price=Decimal("20.00"),
        calculated_price=Decimal("50.00"),
    )


def _payload(name: str, machine_code: str) -> MatrixDeployPayload:
    return MatrixDeployPayload(
        logical_matrix_name=name,
        machine_code=machine_code,
        matrix_multiplier="1.0",
        lines=(_line(),),
    )


def _result(
    name: str,
    machine_code: str,
    status: str,
    reason: str | None,
) -> MatrixDeployResult:
    return MatrixDeployResult(
        logical_matrix_name=name,
        machine_code=machine_code,
        status=status,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
    )


def _runner(
    mongo_database: Database,
    *,
    sync_result: MatrixParseState,
    build_result: BuildMatrixDeployResult,
    deploy_results: tuple[MatrixDeployResult, ...],
    job_id: str = _JOB_ID,
) -> tuple[
    RunDailyMatrixDeployJob,
    MongoMatrixDeployJobRepository,
    MongoMatrixPriceSnapshotStore,
    MongoMatrixWorkerStatusRepository,
]:
    jobs = MongoMatrixDeployJobRepository.from_collection(mongo_database["matrix_deploy_jobs"])
    snapshots = MongoMatrixPriceSnapshotStore(_collection=mongo_database["matrix_price_snapshots"])
    status = MongoMatrixWorkerStatusRepository.from_collection(
        mongo_database["matrix_worker_status"]
    )
    runner = RunDailyMatrixDeployJob(
        matrix_sync=_Sync(sync_result),
        run_build=_Build(build_result),
        deployer=_Deployer(deploy_results),
        job_repository=jobs,
        snapshot_store=snapshots,
        status_repository=status,
        notifier=_Notifier(),
        clock=_Clock([_STARTED, _FINISHED]),
        id_factory=lambda: job_id,
        logger=_Logger(),
    )
    return runner, jobs, snapshots, status


def test_worker_job_persists_applied_snapshot_terminal_job_and_status(
    mongo_database: Database,
) -> None:
    payload = _payload("Snacks", "512")
    runner, _jobs, _snapshots, _status = _runner(
        mongo_database,
        sync_result=_state(_matrix("Snacks", "512")),
        build_result=BuildMatrixDeployResult(payloads=(payload,), skipped_units=()),
        deploy_results=(_result("Snacks", "512", "applied", None),),
    )

    job = runner.run()

    job_doc = mongo_database["matrix_deploy_jobs"].find_one({"_id": _JOB_ID})
    assert job_doc is not None
    assert job_doc["status"] == "completed"
    assert job_doc["finished_at"] == _FINISHED
    assert job_doc["finished_at"] == job.finished_at
    assert len(job_doc["units"]) == 1
    assert job_doc["units"][0]["deploy_status"] == "applied"

    snapshots = list(mongo_database["matrix_price_snapshots"].find({}))
    assert len(snapshots) == 1
    assert snapshots[0]["job_id"] == _JOB_ID
    assert snapshots[0]["machine_code"] == "512"
    assert snapshots[0]["recorded_at"] == job_doc["finished_at"]

    status_doc = mongo_database["matrix_worker_status"].find_one({"_id": "worker"})
    assert status_doc is not None
    assert status_doc["last_job_id"] == _JOB_ID
    assert status_doc["last_job_status"] == "completed"
    assert status_doc["last_successful_job_at"] == _FINISHED


def test_partial_job_persists_only_applied_snapshot(mongo_database: Database) -> None:
    runner, _jobs, _snapshots, _status = _runner(
        mongo_database,
        sync_result=_state(_matrix("A", "1"), _matrix("B", "2")),
        build_result=BuildMatrixDeployResult(
            payloads=(_payload("A", "1"), _payload("B", "2")),
            skipped_units=(),
        ),
        deploy_results=(
            _result("A", "1", "applied", None),
            _result("B", "2", "failed", "bind_failed"),
        ),
        job_id="integration-job-partial",
    )

    job = runner.run()

    assert job.status == "partial"
    job_doc = mongo_database["matrix_deploy_jobs"].find_one({"_id": "integration-job-partial"})
    assert job_doc is not None
    assert job_doc["status"] == "partial"
    assert job_doc["finished_at"] == _FINISHED

    snapshots = list(mongo_database["matrix_price_snapshots"].find({}))
    assert len(snapshots) == 1
    assert snapshots[0]["machine_code"] == "1"
    assert snapshots[0]["recorded_at"] == job_doc["finished_at"]

    status_doc = mongo_database["matrix_worker_status"].find_one({"_id": "worker"})
    assert status_doc is not None
    assert status_doc["last_job_status"] == "partial"
    assert "last_successful_job_at" not in status_doc


def _base_margin() -> BaseMarginParams:
    return curved_margin_params()


def _snapshot_document(
    *,
    job_id: str,
    product_code: str,
) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id=job_id,
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code=product_code,
                product_name="Prev",
                capacity=15,
                purchase_price="80.00",
                calculated_price="100.00",
                deploy_price="100.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


class _MutableStockProvider:
    def __init__(self, *, value: int | None) -> None:
        self.value = value

    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        return self.value


class _RecordingPurchaseReader:
    def __init__(self, prices: dict[str, tuple[str, int]]) -> None:
        self._prices = prices
        self.calls: list[frozenset[str]] = []

    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        self.calls.append(product_codes)
        attributes = {code: self._prices[code] for code in product_codes if code in self._prices}
        return PurchaseAttributesFetchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


def _record(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    matching = [record for record in caplog.records if record.getMessage() == message]
    assert len(matching) == 1
    return matching[0]


def _real_build_job(
    mongo_database: Database,
    *,
    snapshots: MongoMatrixPriceSnapshotStore,
    run_build: RunMatrixDeployBuild,
    job_id: str,
) -> RunDailyMatrixDeployJob:
    clocks = {
        "guard-job-1": ["2026-07-10T00:00:00+00:00", "2026-07-10T00:01:00+00:00"],
        "guard-job-2": ["2026-07-10T00:02:00+00:00", "2026-07-10T00:03:00+00:00"],
    }
    jobs = MongoMatrixDeployJobRepository.from_collection(mongo_database["matrix_deploy_jobs"])
    status = MongoMatrixWorkerStatusRepository.from_collection(
        mongo_database["matrix_worker_status"]
    )
    return RunDailyMatrixDeployJob(
        matrix_sync=_Sync(
            _state(
                EnabledLogicalMatrix(
                    logical_matrix_name="Snacks",
                    machine_codes=("512",),
                    matrix_multiplier=Decimal("1"),
                    cells=(MatrixCatalogCell(1, "New", "NEW"),),
                )
            )
        ),
        run_build=run_build,
        deployer=_Deployer((_result("Snacks", "512", "applied", None),)),
        job_repository=jobs,
        snapshot_store=snapshots,
        status_repository=status,
        notifier=_Notifier(),
        clock=_Clock(clocks[job_id]),
        id_factory=lambda: job_id,
        logger=_Logger(),
    )


def test_substitution_guard_blocks_then_applies_after_stock_drains(
    mongo_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    snapshots = MongoMatrixPriceSnapshotStore(_collection=mongo_database["matrix_price_snapshots"])
    snapshots.save(_snapshot_document(job_id="seed", product_code="OLD"))
    stock = _MutableStockProvider(value=2)
    purchase_reader = _RecordingPurchaseReader(
        {
            "OLD": ("80.00", 15),
            "NEW": ("10.00", 10),
        }
    )
    run_build = RunMatrixDeployBuild(
        snapshot_store=snapshots,
        purchase_reader=purchase_reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={"OLD": Decimal("1"), "NEW": Decimal("1")},
        substitution_guard_enabled=True,
        stock_provider=stock,
    )
    with caplog.at_level(logging.INFO):
        first = _real_build_job(
            mongo_database,
            snapshots=snapshots,
            run_build=run_build,
            job_id="guard-job-1",
        ).run()
    assert first.units[0].sku_stats.product_swap_blocked == 1
    first_line = first.units[0].product_swap_blocked_lines[0]
    assert (first_line.current_product, first_line.desired_product) == ("OLD", "NEW")

    first_doc = mongo_database["matrix_deploy_jobs"].find_one({"_id": "guard-job-1"})
    assert first_doc is not None
    assert first_doc["units"][0]["sku_stats"]["product_swap_blocked"] == 1
    persisted = mongo_database["matrix_price_snapshots"].find_one({"job_id": "guard-job-1"})
    assert persisted is not None
    assert persisted["lines"][0]["product_code"] == "OLD"
    assert persisted["lines"][0]["outcome"] == "product_swap_blocked"
    assert _record(caplog, "matrix_substitution_blocked").job_id == "guard-job-1"

    stock.value = 0
    second = _real_build_job(
        mongo_database,
        snapshots=snapshots,
        run_build=run_build,
        job_id="guard-job-2",
    ).run()
    assert second.units[0].sku_stats.applied == 1
    applied = mongo_database["matrix_price_snapshots"].find_one({"job_id": "guard-job-2"})
    assert applied is not None
    assert applied["lines"][0]["product_code"] == "NEW"
    assert applied["lines"][0]["outcome"] == "applied"
    assert purchase_reader.calls == [
        frozenset({"OLD", "NEW"}),
        frozenset({"OLD", "NEW"}),
    ]
