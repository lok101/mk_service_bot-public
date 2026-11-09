from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime


def _disabled_worker_settings() -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=GoogleFormsSettings.model_construct(
            webhook_secret=SecretStr("dev-webhook-secret"),
            revision_form_token_secret=SecretStr("dev-revision-secret"),
            loading_form_token_secret=SecretStr("dev-loading-secret"),
            revision_form_url="https://forms.example/revision",
            loading_form_url="https://forms.example/loading",
            revision_form_token_entry_id="entry.1",
            loading_form_token_entry_id="entry.2",
            technician_warehouse_inventory_form_url="https://forms.example/warehouse",
            technician_warehouse_inventory_form_token_secret=SecretStr(
                "dev-warehouse-inventory-secret",
            ),
            technician_warehouse_inventory_form_token_entry_id="entry.3",
            token_field_name="token",
        ),
        matrix_automation=MatrixAutomationSettings.model_construct(worker_enabled=False),
    )


class _Status:
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        return None

    def record_terminal_job(self, job: object) -> None:
        return None


class _Scheduler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _Clock:
    def now_utc_iso(self) -> str:
        return "2026-07-13T00:00:00Z"


def _runtime(*, enabled: bool = False) -> MatrixWorkerRuntime:
    return MatrixWorkerRuntime(
        enabled=enabled,
        status_repository=_Status(),
        scheduler=_Scheduler(),
        clock=_Clock(),
    )


def test_matrix_worker_container_exposes_run_and_close_only_worker_dependencies() -> None:
    from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer

    runtime = _runtime()
    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    container = MatrixWorkerContainer(runtime=runtime, persistence=persistence)

    assert hasattr(container, "run")
    assert hasattr(container, "close")
    assert not hasattr(container, "api_app")
    assert not hasattr(container, "machine_ops")
    assert not hasattr(container, "outbox")
    assert not hasattr(container, "forms")
    assert not hasattr(container, "settlement")
    assert not hasattr(container, "reference_data")
    assert not hasattr(container, "photos")
    field_names = set(container.__dataclass_fields__)
    assert field_names == {"runtime", "persistence", "extra_closers"}


def test_matrix_worker_container_close_closes_purchase_http_client() -> None:
    from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer

    closed = {"purchase": False}

    def close_purchase() -> None:
        closed["purchase"] = True

    container = MatrixWorkerContainer(
        runtime=_runtime(),
        persistence=PersistenceBundle(mongo_client=None, redis_client=None),
        extra_closers=(close_purchase,),
    )
    container.close()
    assert closed["purchase"] is True


def test_matrix_worker_container_close_closes_mongo_when_extra_closer_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pymongo import MongoClient

    from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer

    closed = {"purchase": False, "mongo": False}
    mongo_client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )

    def close_purchase() -> None:
        closed["purchase"] = True
        raise RuntimeError("purchase close failed")

    def close_mongo() -> None:
        closed["mongo"] = True

    monkeypatch.setattr(mongo_client, "close", close_mongo)
    container = MatrixWorkerContainer(
        runtime=_runtime(),
        persistence=PersistenceBundle(mongo_client=mongo_client, redis_client=None),
        extra_closers=(close_purchase,),
    )
    with pytest.raises(RuntimeError, match="purchase close failed"):
        container.close()
    assert closed["purchase"] is True
    assert closed["mongo"] is True


def test_matrix_worker_container_does_not_construct_app_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer
    from src.infrastructure.composition.wiring import assemble_matrix_worker as assemble_mod

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("assemble_app_container must not be called")

    monkeypatch.setattr(
        "src.infrastructure.composition.wiring.assemble.assemble_app_container",
        boom,
    )

    fake_runtime = _runtime()
    fake_persistence = PersistenceBundle(mongo_client=None, redis_client=None)

    def fake_assemble(settings: Settings | None = None) -> MatrixWorkerContainer:
        assert settings is not None
        return MatrixWorkerContainer(runtime=fake_runtime, persistence=fake_persistence)

    monkeypatch.setattr(assemble_mod, "assemble_matrix_worker", fake_assemble)

    container = MatrixWorkerContainer.from_settings(_disabled_worker_settings())
    assert container.runtime is fake_runtime
    assert container.persistence is fake_persistence


def test_entrypoint_boots_matrix_worker_without_app_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_matrix_worker

    from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer

    calls: list[str] = []

    class _Ops:
        def stop(self) -> None:
            calls.append("ops_stop")

    fake_runtime = _runtime()
    fake_persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    built = MatrixWorkerContainer(runtime=fake_runtime, persistence=fake_persistence)

    async def fake_run(self: MatrixWorkerContainer) -> None:
        calls.append("run")

    def fake_from_settings(
        cls: type[MatrixWorkerContainer],
        settings: Settings | None = None,
    ) -> MatrixWorkerContainer:
        calls.append("from_settings")
        assert settings is not None
        return built

    def fake_close(self: MatrixWorkerContainer) -> None:
        calls.append("close")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("get_app_container must not be called")

    monkeypatch.setattr(
        run_matrix_worker.MatrixWorkerContainer,
        "from_settings",
        classmethod(fake_from_settings),
    )
    monkeypatch.setattr(run_matrix_worker.MatrixWorkerContainer, "run", fake_run)
    monkeypatch.setattr(run_matrix_worker.MatrixWorkerContainer, "close", fake_close)
    monkeypatch.setattr(run_matrix_worker, "get_settings", _disabled_worker_settings)
    monkeypatch.setattr(
        run_matrix_worker,
        "configure_ops_alert_logging",
        lambda settings: _Ops(),
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.get_app_container",
        boom,
        raising=False,
    )

    asyncio.run(run_matrix_worker.main())
    assert calls == ["from_settings", "run", "close", "ops_stop"]
