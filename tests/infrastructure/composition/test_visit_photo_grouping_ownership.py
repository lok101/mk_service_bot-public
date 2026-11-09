"""Handler visit_photo_grouping: enqueue in app, processor only in worker."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.visit_photo_grouping import (
    VISIT_PHOTO_GROUPING_HANDLER_ID,
    DeliveryKind,
    GroupingDelivery,
)
from src.config.google_forms import GoogleFormsSettings
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.config.object_storage import ObjectStorageSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.config.visit_photo_grouping import VisitPhotoGroupingSettings
from src.config.visit_photo_review import VisitPhotoReviewSettings
from src.domain.machine_operations.events import PhotosSubmitted
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.wiring import wire_visit_photo_grouping_worker as wire_mod
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.composition.wiring.wire_visit_photo_grouping_worker import (
    wire_visit_photo_grouping_worker,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.photo_batches import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.stubs import InMemoryPhotoStorage
from src.infrastructure.visit_photo_grouping import (
    register_visit_photo_grouping,
    subscribe_visit_photo_grouping,
)
from src.infrastructure.visit_photo_grouping.openclip_classifier import OpenClipGroupClassifier
from src.infrastructure.visit_photo_grouping.outbox_handler import VisitPhotoGroupingOutboxHandler

_VALID_CATALOG = (
    '{"groups":['
    '{"group_id":"a","title":"A","required":true,"defects":[]},'
    '{"group_id":"unrecognized","title":"Не удалось определить","required":false,"defects":[]},'
    '{"group_id":"poor_quality","title":"Некачественные фото","required":false,"defects":[]}'
    "]}"
)


def _stub_forms() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
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
    )


def test_app_subscribe_only_when_grouping_enabled() -> None:
    processors = OutboxProcessorRegistry()
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        visit_photo_grouping_enabled=True,
        visit_photo_grouping_handler=None,
    )
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in publisher.handler_ids_for(PhotosSubmitted)
    assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID) is False


def test_app_enabled_still_does_not_register_processor() -> None:
    processors = OutboxProcessorRegistry()
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    subscribe_visit_photo_grouping(publisher=publisher, enabled=True)
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in publisher.handler_ids_for(PhotosSubmitted)
    assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID) is False


def test_worker_disabled_has_no_processor() -> None:
    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        visit_photo_grouping=VisitPhotoGroupingSettings.model_construct(
            enabled=True,
            worker_enabled=False,
            pack_dir="/tmp/pack",
            catalog_path="/tmp/catalog.json",
        ),
        mongodb=MongoSettings.model_construct(uri=None),
    )
    container = wire_visit_photo_grouping_worker(
        settings,
        persistence=PersistenceBundle(mongo_client=None, redis_client=None),
    )
    assert container.runtime.enabled is False
    assert container.outbox_processors is None
    container.close()


def test_worker_enabled_registers_processor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(_VALID_CATALOG, encoding="utf-8")
    pack = tmp_path / "pack"
    group = pack / "reference" / "a"
    group.mkdir(parents=True)
    (group / "a.jpg").write_bytes(b"img")

    class _Enc:
        def encode(self, image_bytes: bytes) -> tuple[float, ...]:
            del image_bytes
            return (1.0, 0.0)

    @dataclass(frozen=True, slots=True)
    class _Permanent:
        def execute(self, batch_id: str) -> GroupingDelivery:
            return GroupingDelivery(
                kind=DeliveryKind.PERMANENT,
                batch_id=batch_id,
                machine_id="m-1",
            )

    monkeypatch.setattr(
        wire_mod,
        "build_photo_storage",
        lambda settings: InMemoryPhotoStorage(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_photo_batch_store",
        lambda settings, client=None: InMemoryPhotoBatchStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_outbox_store",
        lambda settings, client=None: InMemoryOutboxStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_visit_photo_review_deps",
        lambda settings, client=None, photo_batch_store=None: SimpleNamespace(
            catalog=object(),
            assign_batch_groups=object(),
            record_missing_required_group=object(),
        ),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_visit_photo_grouping_handler",
        lambda **kwargs: VisitPhotoGroupingOutboxHandler(_Permanent()),
    )

    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        visit_photo_grouping=VisitPhotoGroupingSettings.model_construct(
            enabled=True,
            worker_enabled=True,
            pack_dir=str(pack),
            catalog_path=str(catalog),
            weights_path="",
        ),
        visit_photo_review=VisitPhotoReviewSettings.model_construct(
            enabled=False,
            catalog_path=str(catalog),
            collection="visit_photo_reviews",
        ),
        mongodb=MongoSettings.model_construct(
            uri="mongodb://localhost/test",
            database="mk_service_bot",
            outbox_poll_interval_seconds=1.0,
        ),
        master_data=MasterDataSettings.model_construct(enabled=False),
        object_storage=ObjectStorageSettings.model_construct(backend="memory"),
    )
    mongo = SimpleNamespace(close=lambda: None)
    container = wire_visit_photo_grouping_worker(
        settings,
        persistence=PersistenceBundle(mongo_client=mongo, redis_client=None),
        encoder=_Enc(),
    )
    assert container.runtime.enabled is True
    assert container.outbox_processors is not None
    assert container.outbox_processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID)
    container.close()


def test_worker_register_helper_registers_processor() -> None:
    @dataclass(frozen=True, slots=True)
    class _Permanent:
        def execute(self, batch_id: str) -> GroupingDelivery:
            return GroupingDelivery(
                kind=DeliveryKind.PERMANENT,
                batch_id=batch_id,
                machine_id="m-1",
            )

    processors = OutboxProcessorRegistry()
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_visit_photo_grouping(
        publisher=publisher,
        processors=processors,
        enabled=True,
        handler=VisitPhotoGroupingOutboxHandler(_Permanent()),
    )
    assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID)
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in publisher.handler_ids_for(PhotosSubmitted)


def test_openclip_classifier_importable_for_worker(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    group = pack / "reference" / "a"
    group.mkdir(parents=True)
    (group / "a.jpg").write_bytes(b"img")

    class _Enc:
        def encode(self, image_bytes: bytes) -> tuple[float, ...]:
            del image_bytes
            return (1.0, 0.0)

    class _Store:
        def get_bytes(self, storage_key: str) -> bytes:
            raise FileNotFoundError(storage_key)

    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_Store(),
        encoder=_Enc(),
        min_score=0.5,
        min_margin=0.02,
    )
    assert classifier.min_score == 0.5
