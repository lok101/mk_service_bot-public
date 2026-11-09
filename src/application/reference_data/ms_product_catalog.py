from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from beartype import beartype

_LOGGER = logging.getLogger(__name__)

MS_CATALOG_HEADER: tuple[str, str, str] = ("code", "name", "entity_kind")
MS_CATALOG_SNAPSHOT_HEADER: tuple[str, str, str, str] = (
    "code",
    "name",
    "entity_kind",
    "archived",
)
_ACCEPTED_HEADERS = frozenset({MS_CATALOG_HEADER, MS_CATALOG_SNAPSHOT_HEADER})


class MsEntityKind(StrEnum):
    PRODUCT = "product"
    BUNDLE = "bundle"


class MsProductCatalogParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MsProductEntry:
    code: str
    name: str
    entity_kind: MsEntityKind
    archived: bool = False


@dataclass(frozen=True, slots=True)
class ParsedMsProductCatalog:
    by_code: dict[str, MsProductEntry]
    name_to_code: dict[str, str]


@beartype
def parse_ms_product_catalog_rows(rows: list[list[str]]) -> ParsedMsProductCatalog:
    if not rows:
        raise MsProductCatalogParseError("empty ms product catalog")
    header = tuple(cell.strip().casefold() for cell in rows[0])
    if header not in _ACCEPTED_HEADERS:
        raise MsProductCatalogParseError(
            f"expected header {MS_CATALOG_HEADER} or {MS_CATALOG_SNAPSHOT_HEADER}, got {rows[0]!r}",
        )
    has_archived = header == MS_CATALOG_SNAPSHOT_HEADER
    by_code: dict[str, MsProductEntry] = {}
    name_to_code: dict[str, str] = {}
    for row in rows[1:]:
        code = (row[0] if len(row) > 0 else "").strip()
        name = (row[1] if len(row) > 1 else "").strip()
        kind_raw = (row[2] if len(row) > 2 else "").strip().casefold()
        if not code:
            _LOGGER.warning(
                "product_catalog_ms_skipped_empty_code",
                extra={"product_name": name},
            )
            continue
        if not name:
            raise MsProductCatalogParseError(f"empty name for code={code}")
        try:
            kind = MsEntityKind(kind_raw)
        except ValueError as exc:
            raise MsProductCatalogParseError(f"bad entity_kind={kind_raw!r}") from exc
        archived = _parse_archived(row) if has_archived else False
        if code in by_code:
            raise MsProductCatalogParseError(f"duplicate code: {code}")
        if name in name_to_code:
            raise MsProductCatalogParseError(f"duplicate name: {name}")
        entry = MsProductEntry(code=code, name=name, entity_kind=kind, archived=archived)
        by_code[code] = entry
        name_to_code[name] = code
    return ParsedMsProductCatalog(by_code=by_code, name_to_code=name_to_code)


@beartype
def build_ms_catalog_snapshot_rows(
    entries: list[MsProductEntry],
) -> list[list[str]]:
    rows = [list(MS_CATALOG_SNAPSHOT_HEADER)]
    for entry in entries:
        archived = "true" if entry.archived else "false"
        rows.append([entry.code, entry.name, entry.entity_kind.value, archived])
    return rows


@beartype
def _parse_archived(row: list[str]) -> bool:
    archived_raw = (row[3] if len(row) > 3 else "").strip().casefold()
    if archived_raw == "true":
        return True
    if archived_raw == "false":
        return False
    raise MsProductCatalogParseError(f"bad archived={archived_raw!r}")
