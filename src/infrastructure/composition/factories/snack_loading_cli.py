from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype
from pydantic import SecretStr

from src.application.matrix_automation import SyncGlobalAbort
from src.application.matrix_automation.loading_policy import DefaultMatrixCellLoadingPolicy
from src.application.snack_loading.ports import (
    MatrixCatalogSync,
    NoOpSnackLoadingFailAfterMoveNotifier,
    SnackLoadingFailAfterMoveNotifier,
    SnackLoadingRunStore,
    SnackMainStockReader,
    SnackMoveClient,
)
from src.application.snack_loading.run_loading import RunSnackLoading
from src.config.settings import Settings
from src.infrastructure.alerting.snack_loading_fail_after_move_notifier import (
    TelegramSnackLoadingFailAfterMoveNotifier,
)
from src.infrastructure.composition.factories.integrations import build_moysklad_client
from src.infrastructure.composition.factories.persistence import build_matrix_snapshot_store
from src.infrastructure.composition.factories.reference_data import (
    build_reference_data_snapshot_store,
)
from src.infrastructure.composition.factories.settlement import build_snack_machine_stock_store
from src.infrastructure.composition.matrix_automation_factory import (
    MsCatalogHydratingMatrixSync,
    build_matrix_reference_data_provider,
    build_matrix_reference_sync,
)
from src.infrastructure.composition.wiring.wire_matrix_worker import build_matrix_catalog_reader
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence
from src.infrastructure.mongodb.snack_loading_runs import MongoSnackLoadingRunStore
from src.infrastructure.snack_loading.food_product_codes import food_product_codes_for_cli
from src.infrastructure.snack_loading.ms_loading import (
    MoySkladSnackMainStockReader,
    MoySkladSnackMoveClient,
    load_food_product_codes,
    load_product_id_to_code,
)
from src.infrastructure.snack_loading.plan_cells import (
    DesiredCatalogIndex,
    SnapshotSnackLoadingCellSource,
)
from src.infrastructure.testing.snack_loading_run_store import InMemorySnackLoadingRunStore


@beartype
@dataclass(slots=True)
class _MatrixReferenceCatalogSync:
    matrix_sync: MsCatalogHydratingMatrixSync
    desired_index: DesiredCatalogIndex

    @beartype
    def sync(self) -> None:
        result = self.matrix_sync.sync()
        if isinstance(result, SyncGlobalAbort):
            raise RuntimeError(result.reason)
        self.desired_index.replace_from_parse_state(result)


@beartype
@dataclass(frozen=True, slots=True)
class _EmptyMainStockReader:
    @beartype
    def available_by_product(self) -> dict[str, Decimal]:
        return {}


@beartype
@dataclass(frozen=True, slots=True)
class _UnconfiguredSnackMoveClient:
    @beartype
    def create_move(
        self,
        *,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        del machine_code, positions
        msg = (
            "MoySklad snack move client requires MOYSKLAD_API_TOKEN and "
            "SNACK_LOADING_MAIN_WAREHOUSE_ID / ORGANIZATION_ID / PROJECT_ID"
        )
        raise RuntimeError(msg)


@beartype
def _build_alert_notifier(settings: Settings) -> SnackLoadingFailAfterMoveNotifier:
    token = settings.telegram.bot_token
    chat_id = settings.telegram.alert_chat_id
    if chat_id is None:
        return NoOpSnackLoadingFailAfterMoveNotifier()
    secret = token if isinstance(token, SecretStr) else SecretStr(str(token))
    return TelegramSnackLoadingFailAfterMoveNotifier(
        bot_token=secret.get_secret_value(),
        chat_id=chat_id,
    )


@beartype
def build_snack_loading_runner(settings: Settings) -> RunSnackLoading:
    persistence = wire_persistence(settings)
    stock_store = build_snack_machine_stock_store(
        settings,
        client=persistence.mongo_client,
    )
    snapshot_store = build_matrix_snapshot_store(
        settings,
        client=persistence.mongo_client,
    )
    desired_index = DesiredCatalogIndex()
    snack = settings.snack_loading
    ms_client = build_moysklad_client(settings.moysklad)

    def _load_food_codes() -> frozenset[str]:
        assert ms_client is not None
        return asyncio.run(
            load_food_product_codes(
                ms_client,
                food_products_path=snack.food_products_path,
                recursive=snack.products_recursive,
            )
        )

    food_product_codes = food_product_codes_for_cli(
        handle_food_products=snack.handle_food_products,
        ms_configured=ms_client is not None,
        load_codes=_load_food_codes,
    )

    cell_source = SnapshotSnackLoadingCellSource(
        snapshot_store=snapshot_store,
        stock_store=stock_store,
        desired_index=desired_index,
        food_product_codes=food_product_codes,
    )

    reference_store = build_reference_data_snapshot_store(
        settings,
        client=persistence.mongo_client,
    )
    provider = build_matrix_reference_data_provider(settings.matrix_automation)
    catalog_reader = build_matrix_catalog_reader(settings)
    matrix_sync = build_matrix_reference_sync(
        settings,
        store=reference_store,
        provider=provider,
        catalog_reader=catalog_reader,
    )
    catalog_sync: MatrixCatalogSync = _MatrixReferenceCatalogSync(
        matrix_sync=matrix_sync,
        desired_index=desired_index,
    )

    main_stock: SnackMainStockReader
    move_client: SnackMoveClient
    if (
        ms_client is not None
        and snack.main_warehouse_id is not None
        and snack.organization_id is not None
        and snack.project_id is not None
    ):
        product_id_to_code = asyncio.run(
            load_product_id_to_code(
                ms_client,
                products_path=snack.products_path,
                recursive=snack.products_recursive,
            )
        )
        main_stock = MoySkladSnackMainStockReader(
            client=ms_client,
            main_warehouse_id=snack.main_warehouse_id,
            product_id_to_code=product_id_to_code,
        )
        move_client = MoySkladSnackMoveClient(
            client=ms_client,
            main_warehouse_id=snack.main_warehouse_id,
            organization_id=snack.organization_id,
            project_id=snack.project_id,
            warehouses_path=snack.warehouses_path,
            warehouses_recursive=snack.warehouses_recursive,
        )
    else:
        main_stock = _EmptyMainStockReader()
        move_client = _UnconfiguredSnackMoveClient()

    if settings.mongodb.is_configured:
        run_store: SnackLoadingRunStore = MongoSnackLoadingRunStore.from_settings(
            settings.mongodb,
            client=persistence.mongo_client,
        )
    else:
        run_store = InMemorySnackLoadingRunStore()

    return RunSnackLoading(
        stock_store=stock_store,
        catalog_sync=catalog_sync,
        cell_source=cell_source,
        main_stock=main_stock,
        move_client=move_client,
        run_store=run_store,
        alert_notifier=_build_alert_notifier(settings),
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=snack.min_move_fraction,
        handle_food_products=snack.handle_food_products,
        machine_interval_seconds=snack.machine_interval_seconds,
        batch_gap_seconds=snack.batch_gap_seconds,
    )
