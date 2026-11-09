from __future__ import annotations

import asyncio
import logging

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import CompanyValidationError, MasterCompany
from src.domain.system_user import AdminPanel
from src.interfaces.admin.companies_view import (
    CompaniesListView,
    CompanyFormView,
    bindings_from_form,
    build_companies_list_view,
    build_company_form_view,
    parse_company_list_status,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    require_panel,
)

_LOGGER = logging.getLogger(__name__)
_COMPANIES_PATH = "/admin/companies"

__all__ = ["register_companies_routes"]


@beartype
def register_companies_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    create = deps.create_company
    update = deps.update_company
    store = deps.company_store
    assert create is not None
    assert update is not None
    assert store is not None

    @router.get("/companies")
    async def companies_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COMPANIES)
        if isinstance(actor, Response):
            return actor
        status = parse_company_list_status(request.query_params.get("status"))
        view = await asyncio.to_thread(build_companies_list_view, store, status=status)
        return _companies_list_page(request, deps, view=view)

    @router.get("/companies/new")
    async def company_new_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COMPANIES)
        if isinstance(actor, Response):
            return actor
        return _company_form_page(request, deps, company=None)

    @router.post("/companies/new")
    async def company_new_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COMPANIES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_companies_origin_reject")
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        name = fields.get("name", "")
        try:

            def _create() -> MasterCompany:
                bindings = bindings_from_form(fields)
                created = create.execute(
                    name=name,
                    bindings=bindings,
                    actor_telegram_user_id=actor,
                    now=deps.now_factory(),
                )
                _refresh_company_display_names(deps)
                return created

            created = await asyncio.to_thread(_create)
        except CompanyValidationError as exc:
            _LOGGER.info("admin_companies_save_reject", extra={"reason": str(exc)})
            return _company_form_page(
                request,
                deps,
                company=None,
                error=str(exc),
                status_code=400,
                posted_name=name,
            )
        except Exception:
            _LOGGER.exception("admin_company_create_failed")
            return Response(status_code=500)
        _LOGGER.info(
            "admin_company_create",
            extra={"actor": actor, "company_id": created.company_id},
        )
        _LOGGER.info("admin_company_workers_directory_stale")
        return RedirectResponse(
            f"{_COMPANIES_PATH}/{created.company_id}",
            status_code=303,
        )

    @router.get("/companies/{company_id:int}")
    async def company_edit_get(request: Request, company_id: int) -> Response:
        actor = require_panel(request, deps, AdminPanel.COMPANIES)
        if isinstance(actor, Response):
            return actor
        existing = await asyncio.to_thread(store.get, company_id)
        if existing is None:
            return Response(status_code=404)
        return _company_form_page(request, deps, company=existing)

    @router.post("/companies/{company_id:int}")
    async def company_edit_post(request: Request, company_id: int) -> Response:
        actor = require_panel(request, deps, AdminPanel.COMPANIES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_companies_origin_reject")
            return Response(status_code=403)
        existing = store.get(company_id)
        if existing is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        name = fields.get("name", "")
        is_active = "is_active" in fields
        try:

            def _update() -> MasterCompany:
                bindings = bindings_from_form(fields)
                updated = update.execute(
                    company_id=company_id,
                    name=name,
                    is_active=is_active,
                    bindings=bindings,
                    actor_telegram_user_id=actor,
                    now=deps.now_factory(),
                )
                _refresh_company_display_names(deps)
                return updated

            await asyncio.to_thread(_update)
        except CompanyValidationError as exc:
            _LOGGER.info("admin_companies_save_reject", extra={"reason": str(exc)})
            current = store.get(company_id)
            if current is None:
                return Response(status_code=404)
            return _company_form_page(
                request,
                deps,
                company=current,
                error=str(exc),
                status_code=400,
                posted_name=name,
                posted_is_active=is_active,
            )
        except Exception:
            _LOGGER.exception("admin_company_update_failed")
            return Response(status_code=500)
        _LOGGER.info(
            "admin_company_update",
            extra={"actor": actor, "company_id": company_id},
        )
        _LOGGER.info("admin_company_workers_directory_stale")
        return RedirectResponse(f"{_COMPANIES_PATH}/{company_id}", status_code=303)


def _refresh_company_display_names(deps: AdminHttpDeps) -> None:
    refresh = deps.refresh_company_display_names
    if refresh is None:
        return
    refresh()


def _companies_list_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    view: CompaniesListView,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    return _TEMPLATES.TemplateResponse(
        request,
        "companies.html",
        page_context(
            request,
            deps,
            rows=view.rows,
            status=view.status,
            error=error,
        ),
        status_code=status_code,
    )


def _company_form_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    company: MasterCompany | None,
    error: str | None = None,
    status_code: int = 200,
    posted_name: str | None = None,
    posted_is_active: bool | None = None,
) -> Response:
    view = build_company_form_view(company)
    if posted_name is not None or posted_is_active is not None:
        view = CompanyFormView(
            company_id=view.company_id,
            name=posted_name if posted_name is not None else view.name,
            is_active=posted_is_active if posted_is_active is not None else view.is_active,
            bindings=view.bindings,
        )
    template = "company_new.html" if company is None else "company_edit.html"
    return _TEMPLATES.TemplateResponse(
        request,
        template,
        page_context(
            request,
            deps,
            company=view,
            error=error,
        ),
        status_code=status_code,
    )
