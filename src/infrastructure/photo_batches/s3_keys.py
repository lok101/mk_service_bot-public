from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import calendar_day_in_timezone
from src.domain.ids import BatchId, MachineId, TechnicianId


@beartype
def content_type_to_extension(content_type: str) -> str:
    normalized = content_type.split(";", maxsplit=1)[0].strip().lower()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/heic": "heic",
    }
    if normalized in mapping:
        return mapping[normalized]
    if "/" in normalized:
        subtype = normalized.split("/", maxsplit=1)[1]
        return "jpg" if subtype == "jpeg" else subtype
    return "bin"


@beartype
def build_loading_photo_object_key(
    *,
    key_prefix: str,
    submitted_at: datetime,
    service_timezone: ZoneInfo,
    technician_id: TechnicianId,
    machine_id: MachineId,
    batch_id: BatchId,
    index: int,
    content_type: str,
) -> str:
    calendar_day = calendar_day_in_timezone(submitted_at, service_timezone).isoformat()
    prefix = key_prefix.strip().strip("/")
    extension = content_type_to_extension(content_type)
    parts = [
        "loading",
        calendar_day,
        technician_id.value,
        machine_id.value,
        batch_id.value,
        f"{index}.{extension}",
    ]
    if prefix:
        return f"{prefix}/{'/'.join(parts)}"
    return "/".join(parts)


@beartype
def build_s3_uri(*, bucket: str, object_key: str) -> str:
    normalized_key = object_key.lstrip("/")
    return f"s3://{bucket}/{normalized_key}"


@beartype
def parse_s3_uri(storage_key: str) -> tuple[str, str]:
    parsed = urlparse(storage_key)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 storage key: {storage_key!r}")
    bucket = parsed.netloc
    object_key = parsed.path.lstrip("/")
    if not object_key:
        raise ValueError(f"S3 storage key must include object path: {storage_key!r}")
    return bucket, object_key
