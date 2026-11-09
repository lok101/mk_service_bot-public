from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.product_identity import DomainProduct
from src.interfaces.admin.planogram_product_options import planogram_product_options

_TEMPLATES = Environment(
    loader=FileSystemLoader("src/interfaces/admin/templates"),
    autoescape=True,
)
_JS = Path("src/interfaces/admin/static/planogram_product_picker.js").read_text(encoding="utf-8")


def _option_product(
    domain_product_id: str,
    number: str,
    name: str,
    *,
    hidden: bool,
    code: str | None,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=number,
        name=name,
        catalog_code=code,
        hidden=hidden,
    )


def _render_picker(
    *,
    domain_product_id: str,
    product_name: str,
    linked: bool,
    show_create: bool,
) -> str:
    template = _TEMPLATES.get_template("_planogram_product_picker.html")
    return template.render(
        domain_product_id=domain_product_id,
        product_name=product_name,
        linked=linked,
        show_create=show_create,
        code_input_name="product_code-0",
        id_input_name="domain_product_id-0",
        product_number="d-1",
        legacy_code="",
        legacy_label="",
    )


def test_planogram_product_options_omit_hidden() -> None:
    store = FakeDomainProductStore()
    store.insert(_option_product("prod-1", "d-1", "Кефир", hidden=False, code=None))
    store.insert(_option_product("prod-2", "d-2", "Скрытый", hidden=True, code="2311"))
    store.insert(_option_product("prod-3", "d-3", "Молоко", hidden=False, code="4500"))
    options = planogram_product_options(store)
    assert [item.domain_product_id for item in options] == ["prod-1", "prod-3"]
    assert options[0].name == "Кефир"
    assert options[0].number == "d-1"
    assert options[0].linked is False
    assert options[1].name == "Молоко"
    assert options[1].number == "d-3"
    assert options[1].linked is True


def test_planogram_product_picker_has_typeahead_without_list_or_create() -> None:
    html = _render_picker(
        domain_product_id="",
        product_name="",
        linked=True,
        show_create=True,
    )
    assert 'aria-label="Список товаров"' not in html
    assert 'aria-label="Новый товар"' not in html
    assert 'class="planogram-product-search"' in html or "planogram-product-search" in html
    assert "planogram-product-create" not in html


def test_planogram_product_picker_selected_shows_link_and_clear() -> None:
    html = _render_picker(
        domain_product_id="prod-1",
        product_name="Кефир",
        linked=False,
        show_create=False,
    )
    assert 'href="/admin/domain-products/prod-1"' in html
    assert 'target="_blank"' in html
    assert "planogram-product-clear" in html
    assert 'aria-label="Список товаров"' not in html


def test_planogram_product_picker_script_has_no_quick_create() -> None:
    assert "/domain-products/quick" not in _JS
    assert "planogram-product-create" not in _JS


def test_planogram_product_picker_script_filters_and_applies_product() -> None:
    assert "planogram-product-search" in _JS
    assert "planogram-domain-product-options" in _JS
    assert "planogram-domain-product-id" in _JS
    assert "planogram-product-link" in _JS


def test_planogram_product_picker_script_clears_selection() -> None:
    assert "planogram-product-clear" in _JS


def test_planogram_product_picker_script_empty_state_message() -> None:
    assert "Ничего не найдено" in _JS


def test_planogram_product_picker_script_unlinked_follows_linked_field() -> None:
    assert "product.linked === false" in _JS
    assert "product.catalog_code == null" not in _JS


def test_planogram_product_picker_script_toggles_tr_unlinked_class() -> None:
    assert "planogram-product-unlinked" in _JS
    assert 'closest("tr")' in _JS or "closest('tr')" in _JS
    assert "classList.toggle" in _JS or ("classList.add" in _JS and "classList.remove" in _JS)


def test_planogram_product_picker_script_toggles_cell_unlinked_class() -> None:
    assert "planogram-product-unlinked" in _JS
    assert 'closest(".planogram-cell")' in _JS or "closest('.planogram-cell')" in _JS
    assert "classList.toggle" in _JS or ("classList.add" in _JS and "classList.remove" in _JS)


def test_planogram_css_popup_is_absolutely_positioned() -> None:
    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    match = re.search(r"\.planogram-product-options\s*\{([^}]*)\}", css)
    assert match is not None
    assert "position: absolute" in match.group(1)


def test_planogram_product_picker_script_arrow_typeahead_keys() -> None:
    # happy: ↑/↓ move highlight; Enter selects; Escape closes
    assert 'event.key === "ArrowDown"' in _JS or 'event.key === "ArrowUp"' in _JS
    assert "ArrowDown" in _JS
    assert "ArrowUp" in _JS
    assert 'event.key === "Enter"' in _JS
    assert 'event.key === "Escape"' in _JS
    assert "aria-selected" in _JS


def test_planogram_product_picker_script_ignores_keys_when_list_closed() -> None:
    # edge: no-open list ignores arrow/enter navigation
    assert "listOpen" in _JS or "!list.hidden" in _JS
    assert "if (!listOpen) return" in _JS
