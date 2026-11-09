from __future__ import annotations

from beartype import beartype

from src.application.reference_data.ms_product_catalog import ParsedMsProductCatalog
from src.application.sheets import ParsedProductCatalog


@beartype
def resolve_product_display_name(
    product_code: str,
    *,
    ms: ParsedMsProductCatalog | None,
    vitrine: ParsedProductCatalog | None,
) -> str:
    code = product_code.strip()
    if not code:
        return ""
    if ms is not None:
        entry = ms.by_code.get(code)
        if entry is not None:
            return entry.name
    if vitrine is not None:
        # Паритет code_index_from_catalog (infra product_catalog_source):
        # каждый code_key есть в lookup.
        key = code.casefold()
        if key in vitrine.code_keys:
            return vitrine.lookup[key].name
    return ""


@beartype
def build_product_display_name_map(
    *,
    ms: ParsedMsProductCatalog | None,
    vitrine: ParsedProductCatalog | None,
) -> dict[str, str]:
    # Vitrine first, then MS overwrite — MS wins on casefold key collision
    # (MS codes are strip-exact; vitrine code_keys are casefolded).
    result: dict[str, str] = {}
    if vitrine is not None:
        for code in vitrine.code_keys:
            name = resolve_product_display_name(code, ms=ms, vitrine=vitrine)
            if not name:
                continue
            result[code.strip().casefold()] = name
    if ms is not None:
        for code in ms.by_code:
            name = resolve_product_display_name(code, ms=ms, vitrine=vitrine)
            if not name:
                continue
            result[code.strip().casefold()] = name
    return result
