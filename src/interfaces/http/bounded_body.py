from __future__ import annotations

from beartype import beartype
from fastapi import HTTPException, Request


@beartype
def reject_oversized_content_length(request: Request, *, max_body_bytes: int) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError:
        declared = 0
    if declared > max_body_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Request body exceeds {max_body_bytes} bytes",
        )


@beartype
async def read_bounded_request_body(
    request: Request,
    *,
    max_body_bytes: int,
) -> bytes:
    reject_oversized_content_length(request, max_body_bytes=max_body_bytes)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Request body exceeds {max_body_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)
