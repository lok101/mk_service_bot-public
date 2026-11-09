from __future__ import annotations

from typing import Any

import pytest

from src.application.micromarket_loading.inventory_form_pages import (
    OFF_PLANOGRAM_PAGE_TITLE,
    InventoryFormPage,
)
from src.infrastructure.google_forms.inventory_qty_validation import (
    inventory_qty_validation_upper,
)
from src.infrastructure.google_forms.micromarket_inventory_forms import (
    DriveMicromarketInventoryFormFactory,
)

_FORM_ID = "mm-form-1"
_RESPONDER_URL = f"https://docs.google.com/forms/d/{_FORM_ID}/viewform"
_PUBLISHED_URL = f"https://docs.google.com/forms/d/{_FORM_ID}/viewform?pub=1"
_PAGES = (
    InventoryFormPage(
        kit_group_id=10,
        product_codes=("SKU1", "SKU2"),
        title="Холод",
    ),
)
_NAMES = {"SKU1": "Coffee Beans", "SKU2": "Tea Bags"}
_QTY_MAX = 30
_PUBLISH_BODY = {
    "publishSettings": {
        "publishState": {
            "isPublished": True,
            "isAcceptingResponses": True,
        }
    }
}


def _noop_set_publish(**kwargs: Any) -> dict[str, Any]:
    del kwargs
    return {}


def _factory(**kwargs: Any) -> DriveMicromarketInventoryFormFactory:
    defaults: dict[str, Any] = {
        "drive_files_copy": lambda **_: {"id": _FORM_ID},
        "forms_batch_update": lambda **_: {},
        "forms_get": lambda **_: {"responderUri": _RESPONDER_URL},
        "forms_set_publish_settings": _noop_set_publish,
        "qty_max": _QTY_MAX,
    }
    defaults.update(kwargs)
    return DriveMicromarketInventoryFormFactory(**defaults)


def _copy(
    factory: DriveMicromarketInventoryFormFactory,
    *,
    pages: tuple[InventoryFormPage, ...] = _PAGES,
    names: dict[str, str] | None = None,
) -> Any:
    return factory.copy_template_and_build_questions(
        template_id="tpl",
        pages=pages,
        product_names=names if names is not None else _NAMES,
        qty_max=_QTY_MAX,
    )


def test_micromarket_drive_factory_copy_includes_parents_when_folder_set() -> None:
    captured: dict[str, Any] = {}

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": _FORM_ID}

    factory = _factory(drive_files_copy=drive_files_copy, copy_folder_id="folder-mm")
    _copy(factory)
    assert captured["body"]["parents"] == ["folder-mm"]


def test_micromarket_drive_factory_copy_omits_parents_when_folder_unset() -> None:
    captured: dict[str, Any] = {}

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": _FORM_ID}

    factory = _factory(drive_files_copy=drive_files_copy)
    _copy(factory)
    assert "parents" not in captured["body"]


def test_micromarket_factory_publishes_when_publish_settings_present() -> None:
    calls: list[str] = []
    publish_captured: dict[str, Any] = {}
    get_count = 0

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        nonlocal get_count
        assert kwargs["formId"] == _FORM_ID
        get_count += 1
        calls.append(f"get{get_count}")
        if get_count == 1:
            return {
                "responderUri": _RESPONDER_URL,
                "publishSettings": {"publishState": {"isPublished": False}},
            }
        return {"responderUri": _PUBLISHED_URL}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("batch")
        return {}

    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        publish_captured.update(kwargs)
        calls.append("publish")
        return {}

    factory = _factory(
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
    )
    copied = _copy(factory)
    assert copied.form_id == _FORM_ID
    assert copied.form_url == _PUBLISHED_URL
    assert publish_captured["formId"] == _FORM_ID
    assert publish_captured["body"] == _PUBLISH_BODY
    assert calls == ["get1", "batch", "publish", "get2"]


def test_micromarket_factory_skips_publish_when_publish_settings_absent() -> None:
    calls: list[str] = []

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("get")
        return {"responderUri": _RESPONDER_URL}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("batch")
        return {}

    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("publish")
        return {}

    factory = _factory(
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
    )
    copied = _copy(factory)
    assert copied.form_url == _RESPONDER_URL
    assert "publish" not in calls
    assert calls == ["get", "batch"]


def test_micromarket_factory_raises_when_set_publish_fails() -> None:
    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise RuntimeError("publish failed")

    factory = _factory(
        forms_get=lambda **_: {
            "responderUri": _RESPONDER_URL,
            "publishSettings": {},
        },
        forms_set_publish_settings=forms_set_publish_settings,
    )
    with pytest.raises(RuntimeError, match="publish failed"):
        _copy(factory)


def test_micromarket_factory_page_break_and_questions_in_page_order() -> None:
    """happy: first page has no pageBreak; later pages break + qty in order."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    pages = (
        InventoryFormPage(kit_group_id=10, product_codes=("SKU1",), title="Холод"),
        InventoryFormPage(
            kit_group_id=None,
            product_codes=("SKU2",),
            title=OFF_PLANOGRAM_PAGE_TITLE,
        ),
    )
    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory, pages=pages)
    requests = captured["body"]["requests"]
    assert requests[0] == {
        "updateFormInfo": {
            "info": {"title": "Холод"},
            "updateMask": "title",
        },
    }
    first_q = requests[1]["createItem"]["item"]
    assert first_q["title"] == "Coffee Beans"
    assert first_q["description"] == "SKU1"
    assert "pageBreakItem" not in first_q
    assert requests[2]["createItem"]["item"]["title"] == OFF_PLANOGRAM_PAGE_TITLE
    assert "pageBreakItem" in requests[2]["createItem"]["item"]
    second_q = requests[3]["createItem"]["item"]
    assert second_q["title"] == "Tea Bags"
    assert second_q["description"] == "SKU2"


def test_micromarket_factory_sets_title_description_without_forms_validation() -> None:
    """happy: title=name, description=code; no Forms REST number validation."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory)
    requests = captured["body"]["requests"]
    assert len(requests) == 3
    assert requests[0]["updateFormInfo"]["info"]["title"] == "Холод"
    first = requests[1]["createItem"]["item"]
    assert first["title"] == "Coffee Beans"
    assert first["description"] == "SKU1"
    question = first["questionItem"]["question"]
    assert question["required"] is True
    assert question["textQuestion"] == {"paragraph": False}
    assert "validation" not in question
    assert inventory_qty_validation_upper(factory.qty_max) == _QTY_MAX


def test_micromarket_factory_falls_back_to_code_when_name_empty() -> None:
    """edge: empty/missing name → title=code."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory, names={"SKU1": "", "SKU2": "  "})
    first = captured["body"]["requests"][1]["createItem"]["item"]
    second = captured["body"]["requests"][2]["createItem"]["item"]
    assert first["title"] == "SKU1"
    assert first["description"] == "SKU1"
    assert second["title"] == "SKU2"


def test_micromarket_factory_only_off_planogram_page() -> None:
    """edge: only off-planogram page — no leading pageBreak."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    pages = (
        InventoryFormPage(
            kit_group_id=None,
            product_codes=("SKU1",),
            title=OFF_PLANOGRAM_PAGE_TITLE,
        ),
    )
    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory, pages=pages, names={"SKU1": "Only"})
    requests = captured["body"]["requests"]
    assert requests[0] == {
        "updateFormInfo": {
            "info": {"title": OFF_PLANOGRAM_PAGE_TITLE},
            "updateMask": "title",
        },
    }
    assert requests[1]["createItem"]["item"]["title"] == "Only"
    assert "pageBreakItem" not in requests[1]["createItem"]["item"]


def test_micromarket_factory_skips_page_break_on_first_page() -> None:
    """edge: six shelves → five pageBreaks (no empty leading section)."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    pages = tuple(
        InventoryFormPage(
            kit_group_id=i,
            product_codes=(f"SKU{i}",),
            title=f"{i}. Полка",
        )
        for i in range(1, 7)
    )
    names = {f"SKU{i}": f"Item {i}" for i in range(1, 7)}
    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory, pages=pages, names=names)
    requests = captured["body"]["requests"]
    page_breaks = [
        r for r in requests if "pageBreakItem" in r.get("createItem", {}).get("item", {})
    ]
    assert len(page_breaks) == 5
    assert page_breaks[0]["createItem"]["item"]["title"] == "2. Полка"
    assert requests[0]["updateFormInfo"]["info"]["title"] == "1. Полка"
