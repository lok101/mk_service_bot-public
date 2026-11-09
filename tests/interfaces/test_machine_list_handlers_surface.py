from __future__ import annotations

from pathlib import Path

import src.interfaces.telegram.machines.handlers as handlers_mod
import src.interfaces.telegram.machines.handlers_common as common_mod
import src.interfaces.telegram.machines.handlers_loading_photos as loading_mod
import src.interfaces.telegram.machines.handlers_maintenance as maintenance_mod
import src.interfaces.telegram.machines.handlers_selection as selection_mod
from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.handlers_loading_photos import LoadingPhotosHandlersMixin
from src.interfaces.telegram.machines.handlers_maintenance import MaintenanceHandlersMixin
from src.interfaces.telegram.machines.handlers_selection import SelectionHandlersMixin


def test_machine_list_handlers_facade_mro_includes_action_mixins() -> None:
    bases = MachineListHandlers.__mro__
    assert SelectionHandlersMixin in bases
    assert MaintenanceHandlersMixin in bases
    assert LoadingPhotosHandlersMixin in bases
    assert CommonHandlersMixin in bases


def test_handlers_action_modules_exist_beside_facade() -> None:
    root = Path(handlers_mod.__file__).resolve().parent
    assert Path(common_mod.__file__).resolve().parent == root
    assert Path(selection_mod.__file__).resolve().parent == root
    assert Path(maintenance_mod.__file__).resolve().parent == root
    assert Path(loading_mod.__file__).resolve().parent == root
    assert HANDLERS_BEARTYPE_CONF is not None


def test_handler_mixins_expose_action_methods() -> None:
    assert hasattr(SelectionHandlersMixin, "on_machine_selected")
    assert hasattr(MaintenanceHandlersMixin, "on_maintenance_completed")
    assert hasattr(LoadingPhotosHandlersMixin, "on_loading_photos_send")
    assert hasattr(CommonHandlersMixin, "_require_technician_id")


def test_handler_mixin_action_methods_are_beartype_wrapped() -> None:
    samples = (
        (SelectionHandlersMixin, "on_machine_selected"),
        (MaintenanceHandlersMixin, "on_maintenance_completed"),
        (LoadingPhotosHandlersMixin, "on_loading_photos_send"),
        (CommonHandlersMixin, "_require_technician_id"),
    )
    for mixin_cls, method_name in samples:
        method = getattr(mixin_cls, method_name)
        assert getattr(method, "__wrapped__", None) is not None, (
            f"{mixin_cls.__name__}.{method_name} is not beartype-wrapped"
        )
