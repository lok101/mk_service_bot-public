from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.infrastructure.photo_batches.s3 import S3PhotoStorage, format_s3_client_error


def test_format_s3_client_error_includes_http_status_when_code_empty() -> None:
    error = ClientError(
        {
            "Error": {"Code": "", "Message": ""},
            "body": {"h1": "400 Bad request"},
            "ResponseMetadata": {
                "HTTPStatusCode": 400,
                "RequestId": "req-1",
                "HTTPHeaders": {"content-type": "text/html"},
            },
        },
        "PutObject",
    )

    message = format_s3_client_error(
        error,
        operation="PutObject",
        bucket="mk-service-bot-photos-prod",
        object_key="mk-service-bot/_probe/x.bin",
    )

    assert "http=400" in message
    assert "code=''" in message
    assert "message=''" in message
    assert "request_id='req-1'" in message
    assert "bucket='mk-service-bot-photos-prod'" in message
    assert "body={'h1': '400 Bad request'}" in message


def test_save_for_batch_wraps_client_error_with_http_status() -> None:
    client = AsyncMock()
    client.put_object.side_effect = ClientError(
        {
            "Error": {"Code": "", "Message": ""},
            "body": {"h1": "400 Bad request"},
            "ResponseMetadata": {"HTTPStatusCode": 400, "RequestId": "req-2"},
        },
        "PutObject",
    )
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client.return_value = client_cm

    storage = S3PhotoStorage(
        bucket="mk-prod",
        endpoint_url="https://firsts3.ru",
        access_key_id="key",
        secret_access_key="secret",
        region="default",
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="mk-service-bot",
        addressing_style="virtual",
        _session=session,
    )

    async def _run() -> str:
        return await storage.save_for_batch(
            batch_id=BatchId("batch-1"),
            index=0,
            data=b"photo",
            content_type="image/jpeg",
            technician_id=TechnicianId("10029"),
            machine_id=MachineId("123"),
            submitted_at=datetime(2026, 11, 5, 4, 51, 30, tzinfo=UTC),
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
            key_prefix="mk-service-bot",
        )

    with pytest.raises(RuntimeError, match=r"S3 PutObject failed: http=400"):
        asyncio.run(_run())

    call_kwargs: dict[str, Any] = session.client.call_args.kwargs
    config = call_kwargs["config"]
    assert config.s3["addressing_style"] == "virtual"
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"


def test_client_kwargs_always_disable_default_s3_checksums() -> None:
    storage = S3PhotoStorage(
        bucket="mk-prod",
        endpoint_url="https://firsts3.ru",
        access_key_id="key",
        secret_access_key="secret",
        region="default",
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="mk-service-bot",
        addressing_style="auto",
    )
    config = storage._client_kwargs()["config"]
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
    assert getattr(config, "s3", None) in (None, {})
