from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal

import pytest
from scripts.bom_admin import _CliDeps, build_parser, main
from tests.application.product_identity.fakes import FakeDomainProductStore

from scripts import bom_admin
from src.application.coffee_bom.migrate_legacy_recipes import (
    LegacyCoffeeRecipe,
    LegacyCoffeeRecipeComponent,
)
from src.application.product_identity.models import DomainProduct
from src.config.mongodb import MongoSettings
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository


@dataclass(frozen=True, slots=True)
class _FakeSettings:
    mongodb: MongoSettings


def _build_fake_deps() -> _CliDeps:
    return _CliDeps(
        recipe_repo=InMemoryCoffeeRecipeRepository(),
        products=None,
        list_legacy_recipes=None,
        refresh_pending=None,
    )


def test_build_parser_parses_import_command() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    args = parser.parse_args(["import", "--file", "recipes.json"])
    assert args.command == "import"
    assert args.file == "recipes.json"


def test_import_command_refuses_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deps = _build_fake_deps()
    monkeypatch.setattr("scripts.bom_admin._build_deps", lambda *, no_refresh: deps)
    exit_code = main(["import", "--file", "recipes.json"])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "deprecated" in err
    assert deps.recipe_repo.list_drink_ids() == ()


def test_upsert_command_refuses_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deps = _build_fake_deps()
    monkeypatch.setattr("scripts.bom_admin._build_deps", lambda *, no_refresh: deps)
    exit_code = main(
        [
            "upsert",
            "--bundle",
            "2301",
            "--name",
            "Latte",
            "--component",
            "coffee-1:1",
        ],
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "deprecated" in err
    assert deps.recipe_repo.list_drink_ids() == ()


def test_show_prints_recipe_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deps = _build_fake_deps()
    deps.recipe_repo.upsert(
        CoffeeRecipe(
            drink_product_id="drink-1",
            name="Latte",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="ing-1",
                    quantity_per_unit=Decimal("30"),
                ),
            ),
        ),
    )
    monkeypatch.setattr("scripts.bom_admin._build_deps", lambda *, no_refresh: deps)

    exit_code = main(["show", "drink-1"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["drink_product_id"] == "drink-1"


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.bom_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )

    with pytest.raises(SystemExit, match="MONGODB_URI"):
        bom_admin._build_deps(no_refresh=True)


def test_migrate_command_maps_legacy_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="drink-1",
            number="D-001",
            name="Latte",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="2301",
        ),
    )
    store.insert(
        DomainProduct(
            domain_product_id="ing-1",
            number="I-001",
            name="Coffee",
            catalog_code="coffee-1",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    repo = InMemoryCoffeeRecipeRepository()
    refreshed: list[bool] = []

    class _Refresh:
        def execute(self) -> object:
            refreshed.append(True)

            class _Result:
                transitioned_to_complete = ()

            return _Result()

    legacy = (
        LegacyCoffeeRecipe(
            bundle_code="2301",
            name="Latte",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="coffee-1",
                    quantity_per_unit=Decimal("12.5"),
                ),
            ),
        ),
    )
    deps = _CliDeps(
        recipe_repo=repo,
        products=store,
        list_legacy_recipes=lambda: legacy,
        refresh_pending=_Refresh(),
    )
    monkeypatch.setattr("scripts.bom_admin._build_deps", lambda *, no_refresh: deps)

    exit_code = main(["migrate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "migrated=1" in out
    assert repo.get("drink-1") is not None
    assert refreshed == [True]


def test_build_parser_has_migrate() -> None:
    args = build_parser().parse_args(["migrate", "--allow-partial"])
    assert args.command == "migrate"
    assert args.allow_partial is True
