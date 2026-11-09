from __future__ import annotations

from datetime import UTC, datetime

from scripts.micromarket_inventory_admin import build_parser, issue_as_of_url

from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.issue_inventory_link import (
    IssueMicromarketInventoryLink,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketInventoryFormRegistry,
    StubMicromarketInventoryFormFactory,
    StubMicromarketInventoryFormsConfig,
)

_ISSUED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _issuer() -> IssueMicromarketInventoryLink:
    return IssueMicromarketInventoryLink(
        registry=InMemoryMicromarketInventoryFormRegistry(),
        factory=StubMicromarketInventoryFormFactory(
            form_id="mm-asof",
            form_url="https://forms.example/asof",
        ),
        forms_settings=StubMicromarketInventoryFormsConfig(),
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.mm",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )


def test_cli_issue_as_of_prints_prefilled_url() -> None:
    pages = (InventoryFormPage(kit_group_id=10, product_codes=("2311",), title="группа 10"),)
    url = issue_as_of_url(
        issuer=_issuer(),
        machine_code="701",
        technician_id="tech-1",
        pages=pages,
    )
    assert "https://forms.example/asof" in url
    assert "entry.mm" in url


def test_cli_parser_has_issue_as_of() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "issue-as-of",
            "--machine-code",
            "701",
            "--technician-id",
            "t1",
        ],
    )
    assert args.command == "issue-as-of"
    assert args.machine_code == "701"
