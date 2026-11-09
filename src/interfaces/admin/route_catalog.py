from __future__ import annotations

from beartype import beartype
from fastapi import FastAPI
from starlette.routing import Mount, Route


@beartype
def collect_admin_routes(app: FastAPI) -> frozenset[tuple[str, str]]:
    collected: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, Mount):
            if route.path.startswith("/admin"):
                collected.add(("MOUNT", route.path))
            continue
        if not isinstance(route, Route):
            continue
        path = route.path
        if not path.startswith("/admin"):
            continue
        for method in route.methods or frozenset():
            if method in {"HEAD", "OPTIONS"}:
                continue
            collected.add((method, path))
    return frozenset(collected)
