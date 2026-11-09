from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import (
    MicromarketMachineMultiplierStore,
    MicromarketPriceChangeJournal,
    MicromarketPricingRulesStore,
    MicromarketProductMultiplierStore,
)
from src.application.micromarket_loading.pricing_stores import (
    InMemoryMicromarketMachineMultiplierStore,
    InMemoryMicromarketPriceChangeJournal,
    InMemoryMicromarketPricingRulesStore,
    InMemoryMicromarketProductMultiplierStore,
)
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.micromarket_pricing import (
    MongoMicromarketMachineMultiplierStore,
    MongoMicromarketPriceChangeJournal,
    MongoMicromarketPricingRulesStore,
    MongoMicromarketProductMultiplierStore,
)


@beartype
def build_micromarket_pricing_rules_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MicromarketPricingRulesStore:
    if not settings.mongodb.is_configured:
        return InMemoryMicromarketPricingRulesStore()
    return MongoMicromarketPricingRulesStore.from_settings(settings.mongodb, client=client)


@beartype
def build_micromarket_product_multiplier_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MicromarketProductMultiplierStore:
    if not settings.mongodb.is_configured:
        return InMemoryMicromarketProductMultiplierStore()
    return MongoMicromarketProductMultiplierStore.from_settings(
        settings.mongodb,
        client=client,
    )


@beartype
def build_micromarket_machine_multiplier_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MicromarketMachineMultiplierStore:
    if not settings.mongodb.is_configured:
        return InMemoryMicromarketMachineMultiplierStore()
    return MongoMicromarketMachineMultiplierStore.from_settings(
        settings.mongodb,
        client=client,
    )


@beartype
def build_micromarket_price_change_journal(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MicromarketPriceChangeJournal:
    if not settings.mongodb.is_configured:
        return InMemoryMicromarketPriceChangeJournal()
    return MongoMicromarketPriceChangeJournal.from_settings(settings.mongodb, client=client)
