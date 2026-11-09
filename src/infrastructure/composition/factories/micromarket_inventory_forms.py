from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.issue_inventory_link import (
    IssueMicromarketInventoryLink,
    default_issue_clock,
)
from src.application.micromarket_loading.ports import (
    MicromarketInventoryFormFactory,
    MicromarketInventoryFormRegistry,
)
from src.application.product_identity.ports import DomainProductStore
from src.config.settings import Settings
from src.infrastructure.google_forms.micromarket_inventory_forms import (
    DriveMicromarketInventoryFormFactory,
)
from src.infrastructure.google_forms.user_oauth_credentials import (
    load_forms_user_oauth_credentials,
    optional_copy_folder_id,
)
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshotStore,
)
from src.infrastructure.mongodb.micromarket_inventory_form_registry import (
    MongoMicromarketInventoryFormRegistry,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketInventoryFormRegistry,
    StubMicromarketInventoryFormFactory,
)
from src.interfaces.admin.deps import KitProductGroupsLoad


@beartype
def build_micromarket_inventory_form_registry(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> MicromarketInventoryFormRegistry:
    if settings.mongodb.is_configured and client is not None:
        return MongoMicromarketInventoryFormRegistry.from_settings(
            settings.mongodb,
            client=client,
        )
    return InMemoryMicromarketInventoryFormRegistry()


@beartype
def build_micromarket_inventory_form_factory(
    settings: Settings,
) -> MicromarketInventoryFormFactory | None:
    credentials_file = settings.google_forms.user_oauth_credentials_file.strip()
    if not credentials_file:
        return None
    if not Path(credentials_file).is_file():
        return None
    from googleapiclient.discovery import build

    credentials = load_forms_user_oauth_credentials(credentials_file)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    forms = build("forms", "v1", credentials=credentials, cache_discovery=False)

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], drive.files().copy(**kwargs).execute())

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], forms.forms().batchUpdate(**kwargs).execute())

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], forms.forms().get(**kwargs).execute())

    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], forms.forms().setPublishSettings(**kwargs).execute())

    return DriveMicromarketInventoryFormFactory(
        drive_files_copy=drive_files_copy,
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
        qty_max=settings.google_forms.inventory_form_qty_max,
        copy_folder_id=optional_copy_folder_id(
            settings.micromarket_loading.inventory_form_copy_folder_id,
        ),
    )


@beartype
def _kit_product_groups_unavailable() -> KitProductGroupsLoad:
    return KitProductGroupsLoad(error="Группы Kit Shop не загрузились", groups=())


@beartype
def build_kit_product_groups_loader(
    kitshop_client: object | None,
    *,
    snapshot_store: KitShopReferenceSnapshotStore | None = None,
    kit_company_id: int | None = None,
) -> Callable[[], KitProductGroupsLoad]:
    """Optional Kit group names from local snapshot (same source as admin)."""
    company_id = kit_company_id
    if company_id is None and isinstance(kitshop_client, KitShopHttpClient):
        company_id = int(kitshop_client.api.account.kit_company_id)
    if snapshot_store is None or company_id is None:
        return _kit_product_groups_unavailable

    def load_kit_product_groups() -> KitProductGroupsLoad:
        snapshot = snapshot_store.get(company_id)
        if snapshot is None:
            return KitProductGroupsLoad(
                error="Группы Kit Shop ещё не загружены",
                groups=(),
            )
        return KitProductGroupsLoad(
            error="",
            groups=tuple((group.group_id, group.group_name) for group in snapshot.groups),
        )

    return load_kit_product_groups


@beartype
def build_issue_micromarket_inventory_link(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
    products: DomainProductStore | None = None,
) -> IssueMicromarketInventoryLink | None:
    mm = settings.micromarket_loading
    now_ok = mm.is_micromarket_inventory_now_configured
    google_ok = mm.is_micromarket_inventory_forms_configured
    if not now_ok and not google_ok:
        return None

    factory = build_micromarket_inventory_form_factory(settings)
    if factory is None:
        if google_ok:
            raise ValueError(
                "Micromarket inventory Forms are configured but Google Forms user OAuth "
                "credentials are missing: set GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE "
                "to enable Drive/Forms template copy for link issue",
            )
        factory = StubMicromarketInventoryFormFactory()

    now_secret = ""
    if mm.inventory_form_now_token_secret is not None:
        now_secret = mm.inventory_form_now_token_secret.get_secret_value()
    as_of_secret = ""
    if mm.inventory_form_as_of_token_secret is not None:
        as_of_secret = mm.inventory_form_as_of_token_secret.get_secret_value()
    if now_ok and not now_secret:
        mm.require_micromarket_inventory_now()
    if google_ok:
        assert mm.inventory_form_now_template_id is not None
        assert mm.inventory_form_as_of_template_id is not None
        assert mm.inventory_form_token_entry_id is not None
        assert now_secret
        assert as_of_secret

    return IssueMicromarketInventoryLink(
        registry=build_micromarket_inventory_form_registry(settings, client=client),
        factory=factory,
        forms_settings=mm,
        field_forms_public_base_url=mm.field_forms_public_base_url,
        now_template_id=mm.inventory_form_now_template_id or "",
        as_of_template_id=mm.inventory_form_as_of_template_id or "",
        token_entry_id=mm.inventory_form_token_entry_id or "entry.unused",
        now_token_secret=now_secret,
        as_of_token_secret=as_of_secret,
        clock=default_issue_clock,
        qty_max=settings.google_forms.inventory_form_qty_max,
        products=products,
    )
