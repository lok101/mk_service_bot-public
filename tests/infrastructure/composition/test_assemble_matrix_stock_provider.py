from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from src.application.snack_loading import DomainMatrixStockProvider
from src.config.google_forms import GoogleFormsSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer
from src.infrastructure.composition.wiring.assemble_matrix_worker import (
    assemble_matrix_worker,
)
from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime


def _settings(*, guard: bool) -> Settings:
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
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=False,
            substitution_guard_enabled=guard,
        ),
    )


def _stub_container(persistence: PersistenceBundle) -> MatrixWorkerContainer:
    class _Status:
        def record_heartbeat(self, *, at: str, enabled: bool) -> None:
            return None

        def record_terminal_job(self, job: object) -> None:
            del job
            return None

    class _Scheduler:
        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _Clock:
        def now_utc_iso(self) -> str:
            return "2026-07-30T00:00:00Z"

    runtime = MatrixWorkerRuntime(
        enabled=False,
        status_repository=_Status(),
        scheduler=_Scheduler(),
        clock=_Clock(),
    )
    return MatrixWorkerContainer(runtime=runtime, persistence=persistence)


def test_assemble_matrix_worker_wires_domain_stock_provider_when_guard_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    persistence = PersistenceBundle(mongo_client=None, redis_client=None)

    def _fake_wire(
        settings: Settings,
        *,
        persistence: PersistenceBundle,
        stock_provider: Any = None,
        deploy_map_store: Any = None,
    ) -> MatrixWorkerContainer:
        del settings, deploy_map_store
        captured["stock_provider"] = stock_provider
        return _stub_container(persistence)

    monkeypatch.setattr(
        "src.infrastructure.composition.wiring.assemble_matrix_worker.wire_matrix_worker",
        _fake_wire,
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.wiring.assemble_matrix_worker.wire_persistence",
        lambda _s: persistence,
    )

    assemble_matrix_worker(_settings(guard=True))

    provider = captured["stock_provider"]
    assert isinstance(provider, DomainMatrixStockProvider)
