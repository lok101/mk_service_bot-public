from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from beartype import beartype
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.types import Lifespan

from src.interfaces.google_forms.rate_limit import WebhookRateLimiter
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps, ReadinessProbe
from src.interfaces.google_forms.webhook.loading import register_loading_routes
from src.interfaces.google_forms.webhook.micromarket_inventory import (
    register_micromarket_inventory_routes,
)
from src.interfaces.google_forms.webhook.revision import register_revision_routes
from src.interfaces.google_forms.webhook.snack_inventory import register_snack_inventory_routes
from src.interfaces.google_forms.webhook.warehouse_inventory import (
    register_warehouse_inventory_routes,
)
from src.interfaces.http.bounded_body import (
    reject_oversized_content_length as reject_oversized_content_length_header,
)


@beartype
def build_google_forms_webhook_app(
    deps: GoogleFormsWebhookDeps,
    *,
    expose_openapi_docs: bool = True,
    readiness: ReadinessProbe | None = None,
    outbox_readiness_max_failed: int = 0,
    lifespan: Lifespan[FastAPI] | None = None,
    rate_limiter: WebhookRateLimiter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="MK Service Bot API",
        docs_url="/docs" if expose_openapi_docs else None,
        redoc_url="/redoc" if expose_openapi_docs else None,
        openapi_url="/openapi.json" if expose_openapi_docs else None,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        if readiness is None:
            return JSONResponse({"status": "ok"})
        reference_data = await asyncio.to_thread(readiness.reference_data_freshness)
        mongo_ok, redis_ok, failed_count = await asyncio.gather(
            asyncio.to_thread(readiness.mongo_ok),
            asyncio.to_thread(readiness.redis_ok),
            asyncio.to_thread(readiness.outbox_failed_count),
        )
        if failed_count > outbox_readiness_max_failed:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unavailable",
                    "reason": "outbox_failed_entries",
                    "failed_count": failed_count,
                    "reference_data": reference_data,
                },
            )
        if mongo_ok and redis_ok:
            return JSONResponse({"status": "ok", "reference_data": reference_data})
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reference_data": reference_data},
        )

    if rate_limiter is not None:

        @app.middleware("http")
        async def webhook_rate_limit(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if request.url.path.startswith("/webhooks/google-forms/"):
                ip = request.client.host if request.client else "unknown"
                if not rate_limiter.check(ip):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too Many Requests"},
                        headers={"Retry-After": str(rate_limiter.retry_after_seconds)},
                    )
            return await call_next(request)

    @app.middleware("http")
    async def reject_oversized_content_length(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            reject_oversized_content_length_header(
                request,
                max_body_bytes=deps.webhook_max_body_bytes,
            )
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    register_revision_routes(app, deps)
    register_loading_routes(app, deps)
    register_warehouse_inventory_routes(app, deps)
    register_snack_inventory_routes(app, deps)
    register_micromarket_inventory_routes(app, deps)
    return app
