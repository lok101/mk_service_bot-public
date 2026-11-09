from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from beartype import beartype
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from src.application.product_identity import (
    FILE_UNREADABLE_TEXT,
    DomainProductImportResult,
    import_domain_products,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.domain_product_import_parse import (
    DomainProductImportParseError,
    parse_domain_product_import_file,
)
from src.interfaces.admin.domain_products_view import build_import_result_view
from src.interfaces.admin.http_common import (
    origin_allowed,
    read_admin_body,
    require_panel,
)

_LOGGER = logging.getLogger(__name__)

__all__ = ["register_domain_products_import_routes"]


@beartype
def register_domain_products_import_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    from src.interfaces.admin.routes.domain_products import _list_page

    store = deps.domain_product_store
    lookup = deps.catalog_product_lookup
    assert store is not None
    assert lookup is not None

    @router.post("/domain-products/import")
    async def domain_products_import_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_domain_products_origin_reject")
            return Response(status_code=403)
        try:
            body = await read_admin_body(request, deps)
        except HTTPException as exc:
            if exc.status_code == 413:
                return Response(status_code=413)
            raise
        upload = await _extract_multipart_file(
            body,
            content_type=request.headers.get("content-type", ""),
        )
        if upload is None:
            _LOGGER.info("admin_domain_products_import_reject")
            return await asyncio.to_thread(
                _list_page,
                request,
                deps,
                store=store,
                lookup=lookup,
                import_result=build_import_result_view(
                    DomainProductImportResult(
                        created=0,
                        linked=0,
                        unchanged=0,
                        failures=(),
                    ),
                    file_phrase=FILE_UNREADABLE_TEXT,
                ),
                status_code=400,
            )
        file_bytes, filename = upload
        try:
            rows = parse_domain_product_import_file(file_bytes, filename=filename)
        except DomainProductImportParseError as exc:
            _LOGGER.info("admin_domain_products_import_reject")
            return await asyncio.to_thread(
                _list_page,
                request,
                deps,
                store=store,
                lookup=lookup,
                import_result=build_import_result_view(
                    DomainProductImportResult(
                        created=0,
                        linked=0,
                        unchanged=0,
                        failures=(),
                    ),
                    file_phrase=exc.message,
                ),
                status_code=400,
            )
        result = await asyncio.to_thread(
            import_domain_products,
            rows,
            store=store,
            lookup=lookup,
            procurement_sync=deps.procurement_sync,
        )
        _LOGGER.info(
            "admin_domain_products_import",
            extra={
                "created": result.created,
                "linked": result.linked,
                "unchanged": result.unchanged,
                "failures_count": len(result.failures),
            },
        )
        return await asyncio.to_thread(
            _list_page,
            request,
            deps,
            store=store,
            lookup=lookup,
            import_result=build_import_result_view(result),
        )


async def _extract_multipart_file(
    body: bytes,
    *,
    content_type: str,
) -> tuple[bytes, str] | None:
    if "multipart/form-data" not in content_type.lower():
        return None

    async def _stream() -> AsyncGenerator[bytes]:
        yield body

    parser = MultiPartParser(
        Headers({"content-type": content_type}),
        _stream(),
        max_part_size=max(len(body), 1),
    )
    try:
        form = await parser.parse()
    except MultiPartException:
        return None
    item = form.get("file")
    if item is None or not isinstance(item, UploadFile):
        return None
    filename = (item.filename or "").strip()
    if not filename:
        await item.close()
        return None
    data = await item.read()
    await item.close()
    return data, filename
