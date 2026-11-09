from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from src.config.object_storage import ObjectStorageSettings
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.infrastructure.photo_batches.s3 import S3PhotoStorage
from src.infrastructure.photo_batches.s3_keys import build_loading_photo_object_key

_MINIO_PORT = 9000
_ACCESS_KEY = "minioadmin"
_SECRET_KEY = "minioadmin"
_BUCKET = "mk-test"


def _start_minio_container() -> DockerContainer:
    container = (
        DockerContainer("minio/minio:latest")
        .with_env("MINIO_ROOT_USER", _ACCESS_KEY)
        .with_env("MINIO_ROOT_PASSWORD", _SECRET_KEY)
        .with_command("server /data")
        .with_exposed_ports(_MINIO_PORT)
        .waiting_for(
            LogMessageWaitStrategy(
                re.compile(r"API:", re.IGNORECASE),
            ),
        )
    )
    container.start()
    return container


def _endpoint_url(container: DockerContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(_MINIO_PORT)
    return f"http://{host}:{port}"


@pytest.fixture(scope="module")
def minio_storage() -> Iterator[S3PhotoStorage]:
    try:
        container = _start_minio_container()
    except Exception as error:
        pytest.skip(f"Could not start MinIO test container: {error}")

    endpoint = _endpoint_url(container)
    storage = S3PhotoStorage.from_settings(
        ObjectStorageSettings.model_validate(
            {
                "PHOTO_STORAGE_BACKEND": "s3",
                "S3_ENDPOINT_URL": endpoint,
                "S3_BUCKET": _BUCKET,
                "S3_ACCESS_KEY_ID": _ACCESS_KEY,
                "S3_SECRET_ACCESS_KEY": _SECRET_KEY,
                "S3_REGION": "us-east-1",
                "S3_KEY_PREFIX": "mk-service-bot",
            },
        ),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    )

    async def _ensure_bucket() -> None:
        async with storage._session.client("s3", **storage._client_kwargs()) as client:
            await client.create_bucket(Bucket=_BUCKET)

    asyncio.run(_ensure_bucket())
    try:
        yield storage
    finally:
        container.stop()


def test_s3_photo_storage_save_get_bytes_and_key_format(minio_storage: S3PhotoStorage) -> None:
    submitted_at = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)
    batch_id = BatchId("batch-s3-1")
    data = b"photo-bytes"

    async def _run() -> str:
        return await minio_storage.save_for_batch(
            batch_id=batch_id,
            index=0,
            data=data,
            content_type="image/jpeg",
            technician_id=TechnicianId("tech-1"),
            machine_id=MachineId("vm-1"),
            submitted_at=submitted_at,
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
            key_prefix="mk-service-bot",
        )

    storage_key = asyncio.run(_run())
    assert storage_key.startswith(f"s3://{_BUCKET}/mk-service-bot/loading/2026-06-05/")
    assert storage_key.endswith("/0.jpg")

    round_trip = asyncio.run(minio_storage.get_bytes(storage_key))
    assert round_trip == data


def test_content_type_to_extension_maps_jpeg_to_jpg() -> None:
    key = build_loading_photo_object_key(
        key_prefix="prefix",
        submitted_at=datetime(2026, 6, 5, tzinfo=UTC),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        batch_id=BatchId("batch-1"),
        index=0,
        content_type="image/jpeg",
    )
    assert key.endswith("0.jpg")


def test_s3_get_bytes_rejects_foreign_bucket() -> None:
    storage = S3PhotoStorage(
        bucket="mk-prod-bucket",
        endpoint_url="http://127.0.0.1:9000",
        access_key_id="key",
        secret_access_key="secret",
        region="us-east-1",
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="mk-service-bot",
    )

    with pytest.raises(ValueError, match="does not match configured bucket"):
        asyncio.run(storage.get_bytes("s3://other-bucket/mk-service-bot/vm/photo.jpg"))


def test_s3_delete_rejects_foreign_bucket() -> None:
    storage = S3PhotoStorage(
        bucket="mk-prod-bucket",
        endpoint_url="http://127.0.0.1:9000",
        access_key_id="key",
        secret_access_key="secret",
        region="us-east-1",
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="mk-service-bot",
    )

    with pytest.raises(ValueError, match="does not match configured bucket"):
        asyncio.run(storage.delete("s3://evil-bucket/path"))


def test_s3_get_bytes_rejects_foreign_key_prefix() -> None:
    storage = S3PhotoStorage(
        bucket="mk-prod-bucket",
        endpoint_url="http://127.0.0.1:9000",
        access_key_id="key",
        secret_access_key="secret",
        region="us-east-1",
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="mk-service-bot",
    )

    with pytest.raises(ValueError, match="does not match configured prefix"):
        asyncio.run(
            storage.get_bytes("s3://mk-prod-bucket/other-prefix/loading/2026-06-05/vm/0.jpg"),
        )
