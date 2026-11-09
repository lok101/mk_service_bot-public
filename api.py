from __future__ import annotations

from typing import Any

from src.infrastructure.composition import get_app_container


class _LazyFastAPIApp:
    """Defer FastAPI build until first request (after bot may register notifier)."""

    def __init__(self) -> None:
        self._app: Any = None

    def _get_app(self) -> Any:
        if self._app is None:
            self._app = get_app_container().api_app
        return self._app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._get_app()(scope, receive, send)


app = _LazyFastAPIApp()
