from __future__ import annotations

from beartype import beartype

from src.application.product_identity import catalog_codes_of
from src.application.product_identity.ports import DomainProductStore


@beartype
def _nonempty_catalog_code(code: str | None) -> str | None:
    if code is None or not code.strip():
        return None
    return code


@beartype
def resolve_ms_catalog_code(
    products: DomainProductStore | None,
    product_code: str,
) -> str | None:
    if products is None:
        return _nonempty_catalog_code(product_code)
    product = products.get_by_number(product_code)
    if product is None:
        return _nonempty_catalog_code(product_code)
    codes = catalog_codes_of(product)
    return codes[0] if codes else None


@beartype
def resolve_planogram_line_ms_catalog_code(
    products: DomainProductStore | None,
    *,
    product_code: str,
    domain_product_id: str | None,
) -> str | None:
    """Resolve MS catalog code for a planogram line.

    Prefer ``domain_product_id`` (prod lines often keep empty ``product_code`` after
    domain-product cutover); fall back to ``product_code`` / number lookup.
    """
    codes = planogram_line_ms_catalog_codes(
        products,
        product_code=product_code,
        domain_product_id=domain_product_id,
    )
    return codes[0] if codes else None


@beartype
def planogram_line_ms_catalog_codes(
    products: DomainProductStore | None,
    *,
    product_code: str,
    domain_product_id: str | None,
) -> tuple[str, ...]:
    """Ordered unique MS catalog-code candidates for a planogram line.

    Domain product primary + extras first, then nonempty ``product_code`` (legacy
    MS code left on the line after cutover / before Save wiped it).
    """
    codes: list[str] = []

    def _add(raw: str | None) -> None:
        code = _nonempty_catalog_code(raw)
        if code is not None and code not in codes:
            codes.append(code)

    if domain_product_id and products is not None:
        product = products.get(domain_product_id)
        if product is not None:
            for item in catalog_codes_of(product):
                _add(item)
    raw_line = product_code.strip()
    if raw_line:
        by_number = products.get_by_number(raw_line) if products is not None else None
        if by_number is not None:
            for item in catalog_codes_of(by_number):
                _add(item)
        else:
            _add(raw_line)
    return tuple(codes)
