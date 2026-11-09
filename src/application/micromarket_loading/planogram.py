from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    MicromarketPriceChangeJournal,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.pricing_stores import (
    MicromarketPriceChangeJournalEntry,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.product_identity import DomainProduct
from src.application.product_identity.ports import DomainProductStore

PriceOrigin = Literal["manual", "calculated"]


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPlanogramLine:
    product_code: str
    target_qty: int
    price_rub: Decimal
    active: bool
    sort_order: int
    kit_group_id: int | None = None
    domain_product_id: str | None = None
    pending_exit: bool = False
    price_origin: PriceOrigin = "manual"


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPlanogramShelf:
    kit_group_id: int
    sort_order: int


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPlanogram:
    machine_code: str
    lines: tuple[MicromarketPlanogramLine, ...]
    updated_at: datetime
    shop_list_status: ShopListPublishStatus = ShopListPublishStatus.UNPUBLISHED
    shop_list_error: str = ""
    shop_list_publication_id: str = ""
    shop_list_catch_up_requested: bool = False
    shelves: tuple[MicromarketPlanogramShelf, ...] | None = None


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketCatalogOption:
    product_code: str
    name: str
    path_name: str = ""


@beartype
def planogram_line_display_name(
    line: MicromarketPlanogramLine,
    *,
    products: DomainProductStore | None = None,
    catalog_names: Mapping[str, str] | None = None,
) -> str:
    domain_id = (line.domain_product_id or "").strip() or None
    if domain_id is not None:
        product = products.get(domain_id) if products is not None else None
        if product is None:
            return "Товар не найден"
        return product.name
    code = line.product_code.strip()
    names = catalog_names or {}
    return names.get(code, code)


@beartype
def planogram_line_sort_key(
    line: MicromarketPlanogramLine,
    *,
    products: DomainProductStore | None = None,
    catalog_names: Mapping[str, str] | None = None,
) -> tuple[str, str, str]:
    name = planogram_line_display_name(line, products=products, catalog_names=catalog_names)
    normalized = name.casefold().replace("ё", "е")
    domain_id = (line.domain_product_id or "").strip()
    code = line.product_code.strip()
    return (normalized, domain_id, code)


@beartype
def _validated_shelf_order(shelves: Sequence[MicromarketPlanogramShelf]) -> tuple[int, ...]:
    seen: set[int] = set()
    order: list[int] = []
    for shelf in shelves:
        if not isinstance(shelf.kit_group_id, int) or shelf.kit_group_id <= 0:
            raise ValueError("Некорректная полка")
        if shelf.kit_group_id in seen:
            raise ValueError("Две полки с одной группой Kit")
        seen.add(shelf.kit_group_id)
        order.append(shelf.kit_group_id)
    return tuple(order)


@beartype
def assemble_planogram_shelves(
    submitted_order: Sequence[int],
    lines: Sequence[MicromarketPlanogramLine],
) -> tuple[MicromarketPlanogramShelf, ...]:
    present: list[int] = []
    seen: set[int] = set()
    for line in lines:
        group_id = line.kit_group_id
        if isinstance(group_id, int) and group_id > 0 and group_id not in seen:
            seen.add(group_id)
            present.append(group_id)
    present_ids = set(present)
    ordered: list[int] = []
    ordered_ids: set[int] = set()
    for group_id in submitted_order:
        if group_id in present_ids and group_id not in ordered_ids:
            ordered.append(group_id)
            ordered_ids.add(group_id)
    for group_id in present:
        if group_id not in ordered_ids:
            ordered.append(group_id)
            ordered_ids.add(group_id)
    return tuple(
        MicromarketPlanogramShelf(kit_group_id=group_id, sort_order=index)
        for index, group_id in enumerate(ordered)
    )


@beartype
@dataclass(frozen=True, slots=True)
class SaveMicromarketPlanogram:
    store: MicromarketPlanogramStore
    catalog_codes: Set[str]
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)
    products: DomainProductStore | None = None
    stock_store: MicromarketDeviceStockStore | None = None
    publisher: object | None = None
    journal: ShopListPublishJournal | None = None
    baseline_store: ShopListLastSucceededSnapshotStore | None = None
    price_journal: MicromarketPriceChangeJournal | None = None
    price_actor: str = "admin"

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        lines: Sequence[MicromarketPlanogramLine],
        shelves: Sequence[MicromarketPlanogramShelf],
        catalog_names: Mapping[str, str] | None = None,
    ) -> MicromarketPlanogram:
        normalized: list[MicromarketPlanogramLine] = []
        seen_codes: set[str] = set()
        seen_domain_ids: set[str] = set()
        selected_catalog_codes: set[str] = set()
        for line in lines:
            domain_id = (line.domain_product_id or "").strip() or None
            code = line.product_code.strip()
            product: DomainProduct | None = None

            if domain_id is not None:
                if self.products is None:
                    raise ValueError("unknown domain_product_id")
                product = self.products.get(domain_id)
                if product is None:
                    raise ValueError("unknown domain_product_id")
                code = ""
            elif code:
                if self.products is not None:
                    mapped = self.products.get_by_catalog_code(code)
                    if mapped is not None:
                        domain_id = mapped.domain_product_id
                        product = mapped
                        code = ""
                    elif code not in self.catalog_codes:
                        raise ValueError(f"unknown product_code: {code}")
                elif code not in self.catalog_codes:
                    raise ValueError(f"unknown product_code: {code}")
            else:
                raise ValueError("empty product_code")

            if domain_id is not None:
                if domain_id in seen_domain_ids:
                    raise ValueError(f"duplicate domain_product_id: {domain_id}")
                seen_domain_ids.add(domain_id)
                if product is not None and product.catalog_code:
                    selected_catalog_codes.add(product.catalog_code)

            if code:
                if code in selected_catalog_codes:
                    raise ValueError("duplicate domain_product_id")
                if code in seen_codes:
                    raise ValueError(f"duplicate product_code: {code}")
                seen_codes.add(code)

            label = _line_label(code=code, domain_id=domain_id, product=product)
            if line.target_qty < 0:
                raise ValueError(f"target_qty must be >= 0 for {label}")
            if line.price_rub != line.price_rub.to_integral_value():
                raise ValueError(f"price_rub must be a whole ruble for {label}")
            if line.price_rub < 1:
                raise ValueError(f"price_rub must be >= 1 for {label}")
            if line.active and (not isinstance(line.kit_group_id, int) or line.kit_group_id <= 0):
                raise ValueError(f"kit_group_id required for {label}")

            normalized.append(
                replace(
                    line,
                    product_code=code,
                    domain_product_id=domain_id,
                    price_rub=line.price_rub.to_integral_value(),
                )
            )

        submitted_order = _validated_shelf_order(shelves)
        for line in normalized:
            group_id = line.kit_group_id
            if isinstance(group_id, int) and group_id > 0:
                continue
            label = _line_label(
                code=line.product_code,
                domain_id=line.domain_product_id,
                product=(
                    self.products.get(line.domain_product_id)
                    if self.products is not None and line.domain_product_id is not None
                    else None
                ),
            )
            raise ValueError(f"Товар «{label}» не на полке")

        removed_for_exit = False
        if self.stock_store is not None:
            stock = self.stock_store.load(machine_code)
            filtered: list[MicromarketPlanogramLine] = []
            for line in normalized:
                if not line.pending_exit:
                    filtered.append(line)
                    continue
                key = _stock_key_for_pending_exit(line, self.products)
                if not key:
                    filtered.append(line)
                    continue
                if stock is None or stock.last_factual_qty(key) != Decimal("0"):
                    filtered.append(line)
                    continue
                removed_for_exit = True
            normalized = filtered

        doc_shelves = assemble_planogram_shelves(submitted_order, normalized)
        shelf_order = {shelf.kit_group_id: shelf.sort_order for shelf in doc_shelves}
        normalized = sorted(
            normalized,
            key=lambda line: (
                shelf_order[line.kit_group_id],  # type: ignore[index]
                line.pending_exit,
                planogram_line_sort_key(line, products=self.products, catalog_names=catalog_names),
            ),
        )
        normalized = [replace(line, sort_order=index) for index, line in enumerate(normalized)]

        previous = self.store.get(machine_code)
        previous_by_identity = (
            {_line_identity(line): line for line in previous.lines} if previous is not None else {}
        )
        resolved: list[MicromarketPlanogramLine] = []
        now = self.now_factory()
        for line in normalized:
            origin = _resolve_price_origin(line, previous_by_identity)
            resolved_line = replace(line, price_origin=origin)
            previous_line = previous_by_identity.get(_line_identity(line))
            if (
                self.price_journal is not None
                and previous_line is not None
                and line.price_rub != previous_line.price_rub
            ):
                self.price_journal.append(
                    MicromarketPriceChangeJournalEntry(
                        machine_id=machine_code,
                        product_code=line.product_code or (line.domain_product_id or ""),
                        old_price_rub=previous_line.price_rub,
                        new_price_rub=line.price_rub,
                        origin="manual",
                        actor=self.price_actor,
                        reason=None,
                        at=now,
                    )
                )
            resolved.append(resolved_line)
        normalized = resolved
        new_keys = _mirror_keys(normalized)
        previous_keys = _mirror_keys(previous.lines) if previous is not None else None
        if previous is None or previous_keys != new_keys:
            status = ShopListPublishStatus.UNPUBLISHED
            error = ""
            publication_id = ""
            catch_up = False
        else:
            status = previous.shop_list_status
            error = previous.shop_list_error
            publication_id = previous.shop_list_publication_id
            catch_up = previous.shop_list_catch_up_requested
        doc = MicromarketPlanogram(
            machine_code=machine_code,
            lines=tuple(normalized),
            updated_at=now,
            shop_list_status=status,
            shop_list_error=error,
            shop_list_publication_id=publication_id,
            shop_list_catch_up_requested=catch_up,
            shelves=doc_shelves,
        )
        self.store.upsert(doc)
        if removed_for_exit and self.publisher is not None:
            from src.application.micromarket_loading.publish_job import (
                enqueue_micromarket_shop_list_publish,
            )
            from src.application.micromarket_loading.shop_list_publish_journal import (
                ShopListPublishTrigger,
            )

            enqueue_micromarket_shop_list_publish(
                store=self.store,
                publisher=self.publisher,  # type: ignore[arg-type]
                machine_code=machine_code,
                now=self.now_factory(),
                products=self.products,
                stock_store=self.stock_store,
                journal=self.journal,
                trigger=ShopListPublishTrigger.PENDING_EXIT,
                baseline_store=self.baseline_store,
            )
        return doc


def _stock_key_for_pending_exit(
    line: MicromarketPlanogramLine,
    products: DomainProductStore | None,
) -> str:
    domain_id = line.domain_product_id
    if domain_id is not None and products is not None:
        product = products.get(domain_id)
        if product is not None:
            return product.number
    return line.product_code.strip()


@beartype
def remove_pending_exit_lines_for_explicit_zeros(
    *,
    planogram_store: MicromarketPlanogramStore,
    machine_code: str,
    quantities: Mapping[str, Decimal],
    products: DomainProductStore | None,
    now: datetime,
) -> bool:
    """Drop pending_exit lines whose stock key has explicit zero in ``quantities``."""
    explicit_zeros = {code for code, qty in quantities.items() if qty == 0}
    if not explicit_zeros:
        return False
    doc = planogram_store.get(machine_code)
    if doc is None:
        return False
    kept: list[MicromarketPlanogramLine] = []
    removed = False
    for line in doc.lines:
        key = _stock_key_for_pending_exit(line, products)
        if line.pending_exit and key in explicit_zeros:
            removed = True
            continue
        kept.append(line)
    if not removed:
        return False
    if doc.shelves is not None:
        shelf_order = {shelf.kit_group_id: shelf.sort_order for shelf in doc.shelves}
        kept = sorted(
            kept,
            key=lambda line: (
                shelf_order[line.kit_group_id],  # type: ignore[index]
                planogram_line_sort_key(line, products=products),
            ),
        )
    new_lines = tuple(replace(line, sort_order=index) for index, line in enumerate(kept))
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=new_lines,
            updated_at=now,
            shop_list_status=doc.shop_list_status,
            shop_list_error=doc.shop_list_error,
            shop_list_publication_id=doc.shop_list_publication_id,
            shop_list_catch_up_requested=doc.shop_list_catch_up_requested,
            shelves=doc.shelves,
        )
    )
    return True


def _line_label(
    *,
    code: str,
    domain_id: str | None,
    product: DomainProduct | None,
) -> str:
    if code:
        return code
    if product is not None and product.name.strip():
        return product.name
    if domain_id is not None:
        return domain_id
    return "?"


def _line_identity(line: MicromarketPlanogramLine) -> tuple[str, str]:
    domain_id = (line.domain_product_id or "").strip()
    if domain_id:
        return ("domain", domain_id)
    return ("code", line.product_code.strip())


def _resolve_price_origin(
    line: MicromarketPlanogramLine,
    previous_by_identity: Mapping[tuple[str, str], MicromarketPlanogramLine],
) -> PriceOrigin:
    previous = previous_by_identity.get(_line_identity(line))
    if previous is None:
        return "manual"
    if line.price_rub != previous.price_rub:
        return "manual"
    return previous.price_origin


def _mirror_keys(
    lines: Sequence[MicromarketPlanogramLine],
) -> frozenset[tuple[str, Decimal, int | None, bool, str | None]]:
    return frozenset(
        (
            line.product_code,
            line.price_rub,
            line.kit_group_id,
            line.active,
            line.domain_product_id,
        )
        for line in lines
    )


@beartype
@dataclass(frozen=True, slots=True)
class GetMicromarketPlanogram:
    store: MicromarketPlanogramStore

    @beartype
    def execute(self, machine_code: str) -> MicromarketPlanogram | None:
        return self.store.get(machine_code)
