from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_inventory_policy import ensure_coffee_policy_profiles
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.product_identity.border_registration import BorderRegistrationStore
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider
from src.application.technician_warehouse.ports import DomainEventPublisher
from src.config.settings import Settings
from src.infrastructure.composition.adapters.border_product_gate import ProductIdentityBorderGate
from src.infrastructure.composition.bundles.technician_warehouse import TechnicianWarehouseBundle
from src.infrastructure.composition.factories.product_identity import (
    build_border_registration_store,
    build_domain_product_store,
    build_form_inventory_policy_store,
)
from src.infrastructure.composition.factories.technician_warehouse import (
    build_accept_technician_warehouse_inventory,
    build_close_technician_warehouse,
    build_observe_technician_warehouse_loading,
    build_technician_warehouse_catalog_resolver,
    build_technician_warehouse_delta_port,
    build_technician_warehouse_executor,
    build_technician_warehouse_import,
    build_technician_warehouse_inventory_link_provider,
    build_technician_warehouse_repository,
    build_technician_warehouse_transfer_reader,
)
from src.infrastructure.field_forms.warehouse_link_providers import (
    technician_warehouse_field_form_issue_enabled,
)
from src.infrastructure.integrations.moysklad.client import MoySkladClient


@beartype
def wire_technician_warehouse(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    form_submission_store: FormSubmissionStore,
    product_code_resolver: ProductCodeResolver,
    provider: ReferenceDataProvider,
    moysklad_client: MoySkladClient | None = None,
    publisher: DomainEventPublisher | None = None,
    domain_products: DomainProductStore | None = None,
    border_registrations: BorderRegistrationStore | None = None,
) -> TechnicianWarehouseBundle:
    repository, event_store = build_technician_warehouse_repository(
        settings,
        client=mongo_client,
    )
    executor = build_technician_warehouse_executor(repository, publisher=publisher)
    # ADR-0083: never auto-build Remap here — only effects passes a live client.
    reader = build_technician_warehouse_transfer_reader(moysklad_client)
    catalog_resolver = build_technician_warehouse_catalog_resolver(provider)
    products = domain_products
    border = border_registrations
    border_gate = None
    if settings.domain_product_identity.enabled:
        if products is None:
            products = build_domain_product_store(
                settings.mongodb,
                settings.domain_product_identity,
                client=mongo_client,
            )
        if border is None:
            border = build_border_registration_store(
                settings.mongodb,
                settings.domain_product_identity,
                client=mongo_client,
            )
        border_gate = ProductIdentityBorderGate(products=products, border=border)
    importer = build_technician_warehouse_import(
        settings,
        reader=reader,
        resolver=catalog_resolver,
        executor=executor,
        border_gate=border_gate,
    )
    delta_port = build_technician_warehouse_delta_port(
        importer=importer,
        executor=executor,
    )
    google_forms = settings.google_forms
    field_forms_base = settings.micromarket_loading.field_forms_public_base_url
    link_products = products
    link_policies = None
    if technician_warehouse_field_form_issue_enabled(
        field_forms_public_base_url=field_forms_base,
        technician_warehouse_inventory_form_url=google_forms.technician_warehouse_inventory_form_url,
    ):
        if link_products is None:
            link_products = build_domain_product_store(
                settings.mongodb,
                settings.domain_product_identity,
                client=mongo_client,
            )
        link_policies = build_form_inventory_policy_store(
            settings.mongodb,
            client=mongo_client,
        )
        ensure_coffee_policy_profiles(link_policies)
    return TechnicianWarehouseBundle(
        executor=executor,
        event_store=event_store,
        importer=importer,
        delta_port=delta_port,
        accept_inventory=build_accept_technician_warehouse_inventory(
            store=form_submission_store,
            resolver=product_code_resolver,
            executor=executor,
            google_forms_settings=google_forms,
        ),
        link_provider=build_technician_warehouse_inventory_link_provider(
            google_forms,
            field_forms_public_base_url=field_forms_base,
            products=link_products,
            policies=link_policies,
        ),
        observe_loading=build_observe_technician_warehouse_loading(executor),
        close_warehouse=build_close_technician_warehouse(
            executor=executor,
            importer=importer,
        ),
    )
