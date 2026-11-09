from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from beartype import beartype
from tests.interfaces.webhook_request_helpers import (
    serialize_webhook_json,
    signed_webhook_headers,
)


@beartype
def post_signed_webhook_http(
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any],
    secret: str,
) -> tuple[int, bytes]:
    body = serialize_webhook_json(payload)
    headers = signed_webhook_headers(body=body, secret=secret)
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()
