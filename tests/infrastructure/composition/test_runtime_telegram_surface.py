from __future__ import annotations

import inspect

from src.infrastructure.composition import runtime_telegram
from src.infrastructure.composition.runtime import ProcessRuntime


def test_runtime_telegram_helpers_take_process_runtime_first() -> None:
    for name in (
        "register_telegram",
        "register_telegram_form_workflow",
        "register_telegram_loading_photos",
    ):
        fn = getattr(runtime_telegram, name)
        params = list(inspect.signature(fn).parameters)
        assert params[0] == "runtime"
        hints = inspect.signature(fn).parameters["runtime"].annotation
        assert hints is ProcessRuntime or hints == "ProcessRuntime"


def test_process_runtime_register_methods_still_present() -> None:
    assert callable(ProcessRuntime.register_telegram)
    assert callable(ProcessRuntime.register_telegram_form_workflow)
    assert callable(ProcessRuntime.register_telegram_loading_photos)
