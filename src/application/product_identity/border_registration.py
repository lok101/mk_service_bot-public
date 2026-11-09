from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.product_identity.commands import add_domain_product_link
from src.application.product_identity.models import CARD_TAKEN_TEXT, DomainProductRejected
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore

BorderStatus = Literal["linked", "ignored", "unregistered"]


@beartype
@dataclass(frozen=True, slots=True)
class BorderQueueDecision:
    ms_code: str
    domain_product_id: str | None = None
    ignored: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class BorderRegistration:
    ms_code: str
    ignored: bool = False


@runtime_checkable
class BorderRegistrationStore(Protocol):
    @beartype
    def get(self, ms_code: str) -> BorderRegistration | None: ...

    @beartype
    def save(self, registration: BorderRegistration) -> None: ...

    @beartype
    def list_ignored(self) -> tuple[BorderRegistration, ...]: ...

    @beartype
    def list_pending(self) -> tuple[BorderRegistration, ...]: ...


@beartype
def border_status(
    ms_code: str,
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
) -> BorderStatus:
    trimmed = ms_code.strip()
    if not trimmed:
        return "unregistered"
    if products.get_by_catalog_code(trimmed) is not None:
        return "linked"
    record = border.get(trimmed)
    if record is not None and record.ignored:
        return "ignored"
    return "unregistered"


@beartype
def ignore_border_code(
    ms_code: str,
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
) -> BorderRegistration:
    trimmed = ms_code.strip()
    if not trimmed:
        raise DomainProductRejected("Кода нет в снимке.")
    if products.get_by_catalog_code(trimmed) is not None:
        raise DomainProductRejected("Карточка уже занята другим товаром.")
    existing = border.get(trimmed)
    if existing is not None and existing.ignored:
        return existing
    record = BorderRegistration(ms_code=trimmed, ignored=True)
    border.save(record)
    return record


@beartype
def unregistered_codes_among(
    codes: tuple[str, ...],
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
) -> tuple[str, ...]:
    found: list[str] = []
    for code in codes:
        trimmed = code.strip()
        if not trimmed:
            continue
        if (
            border_status(trimmed, products=products, border=border) == "unregistered"
            and trimmed not in found
        ):
            found.append(trimmed)
    return tuple(found)


@beartype
def note_unregistered_codes(
    codes: tuple[str, ...],
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
) -> tuple[str, ...]:
    noted = unregistered_codes_among(codes, products=products, border=border)
    for code in noted:
        existing = border.get(code)
        if existing is None:
            border.save(BorderRegistration(ms_code=code, ignored=False))
    return noted


@beartype
def list_unregistered_queue(
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
) -> tuple[str, ...]:
    pending = [item.ms_code for item in border.list_pending()]
    ignored = {item.ms_code for item in border.list_ignored()}
    queue: list[str] = []
    for code in pending:
        if code in ignored:
            continue
        if products.get_by_catalog_code(code) is not None:
            continue
        if code not in queue:
            queue.append(code)
    return tuple(queue)


@beartype
def apply_border_queue(
    decisions: tuple[BorderQueueDecision, ...],
    *,
    products: DomainProductStore,
    border: BorderRegistrationStore,
    lookup: CatalogProductLookup,
) -> None:
    """Apply link/ignore decisions for the unregistered queue (all-or-nothing)."""
    if not decisions:
        return
    queue = set(list_unregistered_queue(products=products, border=border))
    prepared: list[tuple[BorderQueueDecision, str | None]] = []
    for decision in decisions:
        code = decision.ms_code.strip()
        product_id = (decision.domain_product_id or "").strip() or None
        ignored = decision.ignored
        if not code:
            raise DomainProductRejected("Кода нет в снимке.")
        if not ignored and product_id is None:
            # Undecided queue row: skip (partial save).
            continue
        if ignored and product_id is not None:
            raise DomainProductRejected("Для каждой строки укажите ингредиент или «Игнорировать».")
        holder = products.get_by_catalog_code(code)
        if holder is not None and (ignored or holder.domain_product_id != product_id):
            raise DomainProductRejected(CARD_TAKEN_TEXT)
        if code not in queue:
            raise DomainProductRejected(f"Код {code} не в очереди unregistered.")
        if product_id is not None:
            product = products.get(product_id)
            if product is None or product.kind != "coffee_ingredient":
                raise DomainProductRejected("Нужен доменный кофейный ингредиент.")
            if product.hidden:
                raise DomainProductRejected("Нужен доменный кофейный ингредиент.")
        prepared.append(
            (
                BorderQueueDecision(
                    ms_code=code,
                    domain_product_id=product_id,
                    ignored=ignored,
                ),
                product_id,
            )
        )

    for decision, product_id in prepared:
        if decision.ignored:
            ignore_border_code(decision.ms_code, products=products, border=border)
            continue
        assert product_id is not None
        add_domain_product_link(
            product_id,
            decision.ms_code,
            store=products,
            lookup=lookup,
        )


@beartype
class MemoryBorderRegistrationStore:
    def __init__(self) -> None:
        self._by_code: dict[str, BorderRegistration] = {}

    @beartype
    def get(self, ms_code: str) -> BorderRegistration | None:
        return self._by_code.get(ms_code.strip())

    @beartype
    def save(self, registration: BorderRegistration) -> None:
        self._by_code[registration.ms_code] = registration

    @beartype
    def list_ignored(self) -> tuple[BorderRegistration, ...]:
        return tuple(item for item in self._by_code.values() if item.ignored)

    @beartype
    def list_pending(self) -> tuple[BorderRegistration, ...]:
        return tuple(item for item in self._by_code.values() if not item.ignored)
