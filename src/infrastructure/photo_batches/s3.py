from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aioboto3
from beartype import beartype
from botocore.config import Config
from botocore.exceptions import ClientError

from src.config.object_storage import ObjectStorageSettings, S3AddressingStyle
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.infrastructure.photo_batches.s3_keys import (
    build_loading_photo_object_key,
    build_s3_uri,
    parse_s3_uri,
)


@beartype
def format_s3_client_error(
    error: ClientError,
    *,
    operation: str,
    bucket: str,
    object_key: str,
) -> str:
    response = error.response if isinstance(error.response, dict) else {}
    err = response.get("Error")
    err_dict = err if isinstance(err, dict) else {}
    meta = response.get("ResponseMetadata")
    meta_dict = meta if isinstance(meta, dict) else {}
    body = response.get("body")
    return (
        f"S3 {operation} failed: http={meta_dict.get('HTTPStatusCode')!r} "
        f"code={err_dict.get('Code')!r} message={err_dict.get('Message')!r} "
        f"request_id={meta_dict.get('RequestId')!r} body={body!r} "
        f"bucket={bucket!r} key={object_key!r}"
    )


@beartype
@dataclass
class S3PhotoStorage:
    bucket: str
    endpoint_url: str | None
    access_key_id: str
    secret_access_key: str
    region: str | None
    service_timezone: ZoneInfo
    key_prefix: str
    addressing_style: S3AddressingStyle = "auto"
    _session: Any = field(default=None, repr=False)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: ObjectStorageSettings,
        *,
        service_timezone: ZoneInfo,
    ) -> S3PhotoStorage:
        secret = settings.s3_secret_access_key
        if secret is None:
            raise ValueError("S3_SECRET_ACCESS_KEY is required for S3PhotoStorage")
        return cls(
            bucket=settings.s3_bucket.strip(),
            endpoint_url=(settings.s3_endpoint_url.strip() if settings.s3_endpoint_url else None),
            access_key_id=settings.s3_access_key_id.strip(),
            secret_access_key=secret.get_secret_value(),
            region=(settings.s3_region.strip() if settings.s3_region else None),
            service_timezone=service_timezone,
            key_prefix=settings.normalized_key_prefix(),
            addressing_style=settings.s3_addressing_style,
        )

    def __post_init__(self) -> None:
        if self._session is None:
            self._session = aioboto3.Session()

    @beartype
    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.region:
            kwargs["region_name"] = self.region
        # S3-compatible (firsts3 и др.) часто отдают HTML 400 на default CRC
        # headers botocore≥1.36; when_required безопасен и для AWS.
        config_kwargs: dict[str, Any] = {
            "signature_version": "s3v4",
            "request_checksum_calculation": "when_required",
            "response_checksum_validation": "when_required",
        }
        if self.addressing_style != "auto":
            config_kwargs["s3"] = {"addressing_style": self.addressing_style}
        kwargs["config"] = Config(**config_kwargs)
        return kwargs

    @beartype
    async def save_for_batch(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        service_timezone: ZoneInfo,
        key_prefix: str,
    ) -> str:
        object_key = build_loading_photo_object_key(
            key_prefix=key_prefix or self.key_prefix,
            submitted_at=submitted_at,
            service_timezone=service_timezone,
            technician_id=technician_id,
            machine_id=machine_id,
            batch_id=batch_id,
            index=index,
            content_type=content_type,
        )
        try:
            async with self._session.client("s3", **self._client_kwargs()) as client:
                await client.put_object(
                    Bucket=self.bucket,
                    Key=object_key,
                    Body=data,
                    ContentType=content_type,
                )
        except ClientError as error:
            raise RuntimeError(
                format_s3_client_error(
                    error,
                    operation="PutObject",
                    bucket=self.bucket,
                    object_key=object_key,
                ),
            ) from error
        return build_s3_uri(bucket=self.bucket, object_key=object_key)

    @beartype
    async def save(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
    ) -> str:
        raise RuntimeError("use scoped_photo_storage or save_for_batch")

    @beartype
    def _parse_and_validate_storage_key(self, storage_key: str) -> tuple[str, str]:
        bucket, object_key = parse_s3_uri(storage_key)
        if bucket != self.bucket:
            raise ValueError(
                f"S3 bucket {bucket!r} does not match configured bucket {self.bucket!r}",
            )
        prefix = self.key_prefix.strip().strip("/")
        if prefix and not object_key.startswith(f"{prefix}/"):
            raise ValueError(
                f"S3 object key {object_key!r} does not match configured prefix {prefix!r}",
            )
        return bucket, object_key

    @beartype
    async def get_bytes(self, storage_key: str) -> bytes:
        bucket, object_key = self._parse_and_validate_storage_key(storage_key)
        try:
            async with self._session.client("s3", **self._client_kwargs()) as client:
                response = await client.get_object(Bucket=bucket, Key=object_key)
                body = response["Body"]
                data = await body.read()
                return bytes(data)
        except ClientError as error:
            raise RuntimeError(
                format_s3_client_error(
                    error,
                    operation="GetObject",
                    bucket=bucket,
                    object_key=object_key,
                ),
            ) from error

    @beartype
    async def delete(self, storage_key: str) -> None:
        bucket, object_key = self._parse_and_validate_storage_key(storage_key)
        try:
            async with self._session.client("s3", **self._client_kwargs()) as client:
                await client.delete_object(Bucket=bucket, Key=object_key)
        except ClientError as error:
            raise RuntimeError(
                format_s3_client_error(
                    error,
                    operation="DeleteObject",
                    bucket=bucket,
                    object_key=object_key,
                ),
            ) from error
