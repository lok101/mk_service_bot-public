from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.matrix_automation.apply_snack_matrix import (
    ApplySnackMatrix,
    ApplySnackMatrixRejected,
)
from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployResult,
    PriceSnapshotDocument,
)
from src.application.matrix_automation.ports import RunMatrixDeployBuildPort
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.product_identity import DomainProduct
from src.application.product_identity.ports import DomainProductStore


def _layout() -> SnackMachineLayout:
    return SnackMachineLayout(
        machine_code="514",
        logical_matrix_name="514",
        matrix_multiplier=Decimal("1"),
        auto_sync_enabled=False,
        cells=(SnackMachineLayoutCell(1, "SKU1"),),
    )


class _RecordingDeployer:
    def __init__(self, *, status: str) -> None:
        self.status = status
        self.calls: list[list[object]] = []

    def deploy(self, payloads: list[object]) -> list[MatrixDeployResult]:
        self.calls.append(list(payloads))
        payload = payloads[0]
        assert isinstance(payload, MatrixDeployPayload)
        return [
            MatrixDeployResult(
                logical_matrix_name=payload.logical_matrix_name,
                machine_code=payload.machine_code,
                status=self.status,  # type: ignore[arg-type]
                reason=None if self.status == "applied" else "kit_error",
            )
        ]


class _Snapshots:
    def __init__(self) -> None:
        self.documents: list[PriceSnapshotDocument] = []

    def has_unit_snapshot(self, *, machine_code: str, logical_matrix_name: str) -> bool:
        return any(
            d.machine_code == machine_code and d.logical_matrix_name == logical_matrix_name
            for d in self.documents
        )

    def save(self, document: PriceSnapshotDocument) -> None:
        self.documents.append(document)

    def get_latest_line(self, **kwargs: object) -> None:
        del kwargs
        return None

    def list_latest_for_machine(self, **kwargs: object) -> tuple[()]:
        del kwargs
        return ()


class _Jobs:
    def __init__(self) -> None:
        self.inserted: list[object] = []

    def insert(self, job: object) -> None:
        self.inserted.append(job)

    def finalize(self, job: object) -> None:
        del job
        return None


class _Clock:
    def now_utc_iso(self) -> str:
        return "2026-08-28T00:00:00Z"


def _ok_payload() -> MatrixDeployPayload:
    return MatrixDeployPayload(
        logical_matrix_name="514",
        machine_code="514",
        matrix_multiplier="1.0",
        lines=(),
    )


def _ok_build(state: object, **kwargs: object) -> BuildMatrixDeployResult:
    del state, kwargs
    return BuildMatrixDeployResult(payloads=(_ok_payload(),), skipped_units=())


def _apply_product(
    domain_product_id: str,
    name: str,
    catalog_code: str | None,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=f"d-{domain_product_id}",
        name=name,
        catalog_code=catalog_code,
        hidden=False,
    )


def _cmd(
    *,
    margin: InMemoryMatrixBaseMarginStore | None = None,
    snapshots: _Snapshots | None = None,
    deployer: _RecordingDeployer | None = None,
    jobs: _Jobs | None = None,
    layout: SnackMachineLayout | None = None,
    products: DomainProductStore | None = None,
    run_build: RunMatrixDeployBuildPort | Callable[..., BuildMatrixDeployResult] | None = None,
) -> ApplySnackMatrix:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(_layout() if layout is None else layout)
    store = InMemoryMatrixBaseMarginStore() if margin is None else margin
    if margin is None:
        store.save(curved_margin_params())
    return ApplySnackMatrix(
        layouts=layouts,
        base_margin_store=store,
        snapshots=_Snapshots() if snapshots is None else snapshots,
        deployer=_RecordingDeployer(status="applied") if deployer is None else deployer,
        run_build=_ok_build if run_build is None else run_build,
        job_repository=_Jobs() if jobs is None else jobs,
        clock=_Clock(),
        id_factory=lambda: "job-1",
        products=products,
    )


def test_apply_snack_matrix_writes_snapshot() -> None:
    snapshots = _Snapshots()
    deployer = _RecordingDeployer(status="applied")
    _cmd(snapshots=snapshots, deployer=deployer).execute(
        machine_code="514", actor_telegram_user_id=1
    )
    assert snapshots.has_unit_snapshot(machine_code="514", logical_matrix_name="514") is True
    assert len(deployer.calls) == 1


def test_apply_snack_matrix_sets_admin_apply_trigger() -> None:
    jobs = _Jobs()
    _cmd(jobs=jobs).execute(machine_code="514", actor_telegram_user_id=1)
    assert jobs.inserted[0].trigger == "admin_apply"


def test_apply_snack_matrix_redeploys_with_existing_snapshot() -> None:
    snapshots = _Snapshots()
    snapshots.save(
        PriceSnapshotDocument(
            job_id="old",
            machine_code="514",
            logical_matrix_name="514",
            recorded_at="2026-08-01T00:00:00Z",
            lines=(),
        )
    )
    deployer = _RecordingDeployer(status="applied")
    _cmd(snapshots=snapshots, deployer=deployer).execute(
        machine_code="514", actor_telegram_user_id=1
    )
    assert len(deployer.calls) == 1


def test_apply_snack_matrix_rejects_without_base_margin() -> None:
    deployer = _RecordingDeployer(status="applied")
    with pytest.raises(ApplySnackMatrixRejected) as exc:
        _cmd(margin=InMemoryMatrixBaseMarginStore(), deployer=deployer).execute(
            machine_code="514", actor_telegram_user_id=1
        )
    assert exc.value.code == "base_margin_not_loaded"
    assert deployer.calls == []


def test_apply_snack_matrix_deploy_fail_skips_snapshot() -> None:
    snapshots = _Snapshots()
    deployer = _RecordingDeployer(status="failed")
    with pytest.raises(ApplySnackMatrixRejected) as exc:
        _cmd(snapshots=snapshots, deployer=deployer).execute(
            machine_code="514", actor_telegram_user_id=1
        )
    assert exc.value.code == "deploy_failed"
    assert snapshots.has_unit_snapshot(machine_code="514", logical_matrix_name="514") is False


def test_apply_snack_matrix_skips_deploy_when_no_publishable_code() -> None:
    products = FakeDomainProductStore()
    products.insert(_apply_product("prod-1", "Кефир", None))
    deployer = _RecordingDeployer(status="applied")
    jobs = _Jobs()
    layout = SnackMachineLayout(
        machine_code="514",
        logical_matrix_name="514",
        matrix_multiplier=Decimal("1"),
        auto_sync_enabled=False,
        cells=(SnackMachineLayoutCell(1, None, domain_product_id="prod-1"),),
    )
    with pytest.raises(ApplySnackMatrixRejected) as caught:
        _cmd(layout=layout, products=products, deployer=deployer, jobs=jobs).execute(
            machine_code="514",
            actor_telegram_user_id=1,
        )
    assert caught.value.code == "nothing_to_send"
    assert deployer.calls == []
    assert jobs.inserted == []


def test_apply_snack_matrix_sends_live_catalog_code() -> None:
    products = FakeDomainProductStore()
    products.insert(_apply_product("prod-1", "Кефир", "2311"))
    seen: list[object] = []

    def _capture(state: object, **kwargs: object) -> BuildMatrixDeployResult:
        del kwargs
        seen.append(state)
        return _ok_build(state)

    layout = SnackMachineLayout(
        machine_code="514",
        logical_matrix_name="514",
        matrix_multiplier=Decimal("1"),
        auto_sync_enabled=False,
        cells=(SnackMachineLayoutCell(1, None, domain_product_id="prod-1"),),
    )
    _cmd(layout=layout, products=products, run_build=_capture).execute(
        machine_code="514",
        actor_telegram_user_id=1,
    )
    state = seen[0]
    assert state.enabled_matrices[0].cells[0].product_code == "2311"
