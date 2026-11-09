from __future__ import annotations

from typing import Any, cast

from beartype import beartype
from pymongo import MongoClient

from src.application.snack_loading.issue_inventory_link import (
    IssueSnackInventoryLink,
    default_issue_clock,
)
from src.application.snack_loading.ports import (
    SnackInventoryCellsSource,
    SnackInventoryFormFactory,
    SnackInventoryFormRegistry,
)
from src.config.settings import Settings
from src.infrastructure.composition.factories.persistence import build_matrix_snapshot_store
from src.infrastructure.google_forms.snack_inventory_forms import DriveSnackInventoryFormFactory
from src.infrastructure.google_forms.user_oauth_credentials import (
    load_forms_user_oauth_credentials,
    optional_copy_folder_id,
)
from src.infrastructure.mongodb.snack_inventory_form_registry import (
    MongoSnackInventoryFormRegistry,
)
from src.infrastructure.snack_loading.inventory_cells import SnapshotSnackInventoryCellsSource
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackInventoryFormRegistry


@beartype
def build_snack_inventory_form_registry(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> SnackInventoryFormRegistry:
    if settings.mongodb.is_configured and client is not None:
        return MongoSnackInventoryFormRegistry.from_settings(
            settings.mongodb,
            client=client,
        )
    return InMemorySnackInventoryFormRegistry()


@beartype
def build_snack_inventory_form_factory(
    settings: Settings,
) -> SnackInventoryFormFactory | None:
    credentials_file = settings.google_forms.user_oauth_credentials_file.strip()
    if not credentials_file:
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

    return DriveSnackInventoryFormFactory(
        drive_files_copy=drive_files_copy,
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
        qty_max=settings.google_forms.inventory_form_qty_max,
        copy_folder_id=optional_copy_folder_id(
            settings.snack_loading.inventory_form_copy_folder_id,
        ),
    )


@beartype
def build_snack_inventory_cells_source(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> SnackInventoryCellsSource:
    return SnapshotSnackInventoryCellsSource(
        snapshot_store=build_matrix_snapshot_store(settings, client=client),
    )


@beartype
def build_issue_snack_inventory_link(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> IssueSnackInventoryLink | None:
    snack = settings.snack_loading
    if not snack.is_snack_inventory_forms_configured:
        return None
    factory = build_snack_inventory_form_factory(settings)
    if factory is None:
        raise ValueError(
            "Snack inventory Forms are configured but Google Forms user OAuth "
            "credentials are missing: set GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE "
            "to enable Drive/Forms template copy for link issue",
        )
    assert snack.inventory_form_now_template_id is not None
    assert snack.inventory_form_as_of_template_id is not None
    assert snack.inventory_form_token_entry_id is not None
    assert snack.inventory_form_now_token_secret is not None
    assert snack.inventory_form_as_of_token_secret is not None
    return IssueSnackInventoryLink(
        registry=build_snack_inventory_form_registry(settings, client=client),
        factory=factory,
        forms_settings=snack,
        now_template_id=snack.inventory_form_now_template_id,
        as_of_template_id=snack.inventory_form_as_of_template_id,
        token_entry_id=snack.inventory_form_token_entry_id,
        now_token_secret=snack.inventory_form_now_token_secret.get_secret_value(),
        as_of_token_secret=snack.inventory_form_as_of_token_secret.get_secret_value(),
        clock=default_issue_clock,
        qty_max=settings.google_forms.inventory_form_qty_max,
    )
