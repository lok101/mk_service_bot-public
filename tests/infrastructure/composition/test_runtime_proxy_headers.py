from __future__ import annotations

import inspect

from src.infrastructure.composition import runtime as runtime_mod


def test_run_api_uvicorn_config_enables_proxy_headers() -> None:
    assert "172.16.0.0/12" in runtime_mod._UVICORN_FORWARDED_ALLOW_IPS
    source = inspect.getsource(runtime_mod.ProcessRuntime.run_api)
    assert "proxy_headers=True" in source
    assert "forwarded_allow_ips=_UVICORN_FORWARDED_ALLOW_IPS" in source
