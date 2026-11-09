from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from src.application.reference_data.ms_product_catalog import MsEntityKind
from src.infrastructure.reference_data.ms_assortment_reader import (
    MoySkladProductCatalogAssortmentReader,
    ProductFolderNotFoundError,
)

_FOLDER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _FakeClient:
    def __init__(
        self,
        *,
        folders: dict[str, list[Mapping[str, Any]]] | None = None,
        pages: dict[str, list[list[Mapping[str, Any]]]] | None = None,
    ) -> None:
        self.folders = folders or {}
        self.pages = pages or {}
        self.calls: list[dict[str, Any]] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        self.calls.append(
            {
                "entity_path": entity_path,
                "filter_expr": filter_expr,
                "limit": limit,
                "offset": offset,
            },
        )
        if entity_path == "productfolder":
            return list(self.folders.get(filter_expr, []))
        key = f"{entity_path}:{filter_expr}"
        sequence = self.pages.get(key, [[]])
        page_idx = offset // limit
        if page_idx >= len(sequence):
            return []
        return list(sequence[page_idx])


def test_list_by_folder_ids_resolves_and_filters() -> None:
    filt = "pathName~=Основной склад/СНЕК;archived=true;archived=false"
    client = _FakeClient(
        folders={
            f"id={_FOLDER}": [
                {"name": "СНЕК", "pathName": "Основной склад"},
            ],
        },
        pages={
            f"product:{filt}": [
                [
                    {"code": "a", "name": "A", "archived": True},
                    {"code": "b", "name": "B", "archived": False},
                    {"code": "  ", "name": "Skip", "archived": False},
                ],
            ],
        },
    )
    reader = MoySkladProductCatalogAssortmentReader(client)
    entries = asyncio.run(
        reader.list_by_folder_ids(
            entity_kind="product",
            folder_ids=(_FOLDER,),
        ),
    )
    assert {e.code for e in entries} == {"a", "b"}
    assert all(e.entity_kind is MsEntityKind.PRODUCT for e in entries)
    assert reader.skipped_empty_code == 1
    assert client.calls[0]["entity_path"] == "productfolder"
    assert f"id={_FOLDER}" in client.calls[0]["filter_expr"]
    assert "pathName~=Основной склад/СНЕК" in client.calls[1]["filter_expr"]


def test_list_by_folder_ids_root_folder_name_only() -> None:
    """edge: folder without parent pathName → filter by name alone."""
    filt = "pathName~=Root;archived=true;archived=false"
    client = _FakeClient(
        folders={f"id={_FOLDER}": [{"name": "Root", "pathName": ""}]},
        pages={f"product:{filt}": [[{"code": "x", "name": "X"}]]},
    )
    reader = MoySkladProductCatalogAssortmentReader(client)
    entries = asyncio.run(
        reader.list_by_folder_ids(entity_kind="product", folder_ids=(_FOLDER,)),
    )
    assert [e.code for e in entries] == ["x"]


def test_list_by_folder_ids_unknown_folder_fails_closed() -> None:
    """error: missing productfolder → ProductFolderNotFoundError."""
    client = _FakeClient(folders={}, pages={})
    reader = MoySkladProductCatalogAssortmentReader(client)
    with pytest.raises(ProductFolderNotFoundError):
        asyncio.run(
            reader.list_by_folder_ids(entity_kind="product", folder_ids=(_FOLDER,)),
        )


def test_list_maps_archived_flag_from_json() -> None:
    filt = "pathName~=goods/food;archived=true;archived=false"
    client = _FakeClient(
        folders={f"id={_FOLDER}": [{"name": "food", "pathName": "goods"}]},
        pages={
            f"product:{filt}": [
                [
                    {"code": "arch", "name": "Arch", "archived": True},
                    {"code": "live", "name": "Live", "archived": False},
                ],
            ],
        },
    )
    reader = MoySkladProductCatalogAssortmentReader(client)
    entries = asyncio.run(
        reader.list_by_folder_ids(entity_kind="product", folder_ids=(_FOLDER,)),
    )
    by_code = {e.code: e for e in entries}
    assert by_code["arch"].archived is True
    assert by_code["live"].archived is False


def test_folder_path_name_cached_between_list_calls() -> None:
    filt = "pathName~=Основной склад/СНЕК;archived=true;archived=false"
    client = _FakeClient(
        folders={
            f"id={_FOLDER}": [
                {"name": "СНЕК", "pathName": "Основной склад"},
            ],
        },
        pages={f"product:{filt}": [[{"code": "a", "name": "A"}]]},
    )
    reader = MoySkladProductCatalogAssortmentReader(client)
    asyncio.run(
        reader.list_by_folder_ids(entity_kind="product", folder_ids=(_FOLDER,)),
    )
    folder_calls_after_first = sum(
        1 for call in client.calls if call["entity_path"] == "productfolder"
    )
    asyncio.run(
        reader.list_by_folder_ids(entity_kind="product", folder_ids=(_FOLDER,)),
    )
    folder_calls_after_second = sum(
        1 for call in client.calls if call["entity_path"] == "productfolder"
    )
    assert folder_calls_after_first == 1
    assert folder_calls_after_second == 1
