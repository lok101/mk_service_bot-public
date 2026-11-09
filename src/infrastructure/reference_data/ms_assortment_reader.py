from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from beartype import beartype

from src.application.reference_data.ms_product_catalog import MsEntityKind, MsProductEntry

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ProductCatalogMsEntityListClient(Protocol):
    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]: ...


def _archived_path_filter(path_name: str) -> str:
    return f"pathName~={path_name};archived=true;archived=false"


class ProductFolderNotFoundError(ValueError):
    """Raised when a configured MoySklad productfolder id cannot be resolved."""


@beartype
@dataclass
class MoySkladProductCatalogAssortmentReader:
    _client: ProductCatalogMsEntityListClient
    page_limit: int = 1000
    skipped_empty_code: int = 0
    _folder_path_by_id: dict[UUID, str] = field(default_factory=dict, repr=False)

    @beartype
    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        kind = MsEntityKind(entity_kind)
        entries: list[MsProductEntry] = []
        for folder_id in folder_ids:
            path_name = await self._resolve_folder_path_name(folder_id)
            entries.extend(await self._list_path(entity_kind=kind, path_name=path_name))
        return entries

    @beartype
    async def _resolve_folder_path_name(self, folder_id: UUID) -> str:
        cached = self._folder_path_by_id.get(folder_id)
        if cached is not None:
            return cached
        rows = await self._client.get_entity_list(
            entity_path="productfolder",
            filter_expr=f"id={folder_id}",
            limit=1,
            offset=0,
        )
        if not rows:
            raise ProductFolderNotFoundError(f"productfolder not found: {folder_id}")
        row = rows[0]
        raw_name = row.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            raise ProductFolderNotFoundError(f"productfolder has empty name: {folder_id}")
        raw_parent = row.get("pathName")
        parent = raw_parent.strip() if isinstance(raw_parent, str) else ""
        path_name = f"{parent}/{name}" if parent else name
        self._folder_path_by_id[folder_id] = path_name
        return path_name

    @beartype
    async def _list_path(
        self,
        *,
        entity_kind: MsEntityKind,
        path_name: str,
    ) -> list[MsProductEntry]:
        filter_expr = _archived_path_filter(path_name)
        entries: list[MsProductEntry] = []
        offset = 0
        while True:
            rows = await self._client.get_entity_list(
                entity_path=entity_kind.value,
                filter_expr=filter_expr,
                limit=self.page_limit,
                offset=offset,
            )
            if not rows:
                break
            for row in rows:
                entry = self._row_to_entry(row, entity_kind=entity_kind)
                if entry is not None:
                    entries.append(entry)
            offset += self.page_limit
            if len(rows) < self.page_limit:
                break
        return entries

    @beartype
    def _row_to_entry(
        self,
        row: Mapping[str, Any],
        *,
        entity_kind: MsEntityKind,
    ) -> MsProductEntry | None:
        raw_code = row.get("code")
        raw_name = row.get("name")
        code = raw_code.strip() if isinstance(raw_code, str) else ""
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not code:
            self.skipped_empty_code += 1
            _LOGGER.warning(
                "product_catalog_ms_skipped_empty_code",
                extra={"product_name": name},
            )
            return None
        return MsProductEntry(
            code=code,
            name=name,
            entity_kind=entity_kind,
            archived=bool(row.get("archived")),
        )
