from __future__ import annotations

from beartype import beartype
from fastapi import APIRouter

from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.technicians import register_technicians_routes
from src.interfaces.admin.routes.users import register_system_users_routes

__all__ = ["register_people_routes"]


@beartype
def register_people_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    if deps.system_user_store is not None and deps.save_system_users is not None:
        register_system_users_routes(router, deps)
    if deps.technicians_enabled and deps.save_field_staff is not None:
        register_technicians_routes(router, deps)
