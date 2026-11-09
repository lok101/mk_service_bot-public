from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from beartype import beartype

from src.domain.form_submission import FormAnswer
from src.domain.product_catalog import ProductSpec, ProductUnit
from src.domain.quantities import QuantityInputMode

EMPTY_INVENTORY_LINES_ERROR = "Inventory form has no product lines"


class QuantityValidationError(ValueError):
    """Raised when form quantity cannot be parsed or does not fit domain rules."""


class SuspiciousUnitMismatchError(QuantityValidationError):
    """Raised when entered unit likely does not match expected interpretation."""


@beartype
@dataclass(frozen=True, slots=True)
class ValidatedInventoryLine:
    product_spec: ProductSpec
    quantity: Decimal


@beartype
def parse_validated_inventory_lines(
    answers: tuple[FormAnswer, ...],
    *,
    excluded_titles: frozenset[str],
    product_specs: dict[str, ProductSpec],
    mode: QuantityInputMode,
    allow_empty: bool,
    apply_stock_range: bool,
    allow_zero: bool,
    max_packages: Decimal | None = None,
) -> list[ValidatedInventoryLine]:
    lines: list[ValidatedInventoryLine] = []

    for answer in answers:
        title = answer.title.strip()
        if not title or title in excluded_titles:
            continue

        spec = product_specs.get(title)
        if spec is None:
            raise QuantityValidationError(
                f"Product {title!r} not found in product catalog",
            )

        amount = parse_raw_quantity(value=answer.value, product_name=title)
        validate_quantity_for_mode(
            amount=amount,
            spec=spec,
            mode=mode,
            apply_stock_range=apply_stock_range,
            allow_zero=allow_zero,
            max_packages=max_packages,
        )

        lines.append(
            ValidatedInventoryLine(
                product_spec=spec,
                quantity=amount,
            ),
        )

    if not lines and not allow_empty:
        raise QuantityValidationError(EMPTY_INVENTORY_LINES_ERROR)

    return lines


@beartype
def parse_raw_quantity(*, value: str, product_name: str) -> Decimal:
    normalized = value.replace(",", ".").strip()
    if not normalized:
        raise QuantityValidationError(
            f"Invalid quantity for product {product_name!r}: {value!r}",
        )

    try:
        return Decimal(normalized)
    except InvalidOperation as error:
        raise QuantityValidationError(
            f"Invalid quantity for product {product_name!r}: {value!r}",
        ) from error


@beartype
def validate_quantity_for_mode(
    *,
    amount: Decimal,
    spec: ProductSpec,
    mode: QuantityInputMode,
    apply_stock_range: bool = True,
    allow_zero: bool,
    max_packages: Decimal | None = None,
) -> None:
    if amount < 0:
        raise QuantityValidationError(
            f"Quantity for product {spec.name!r} must be positive, got {amount}",
        )
    if amount == 0 and not allow_zero:
        raise QuantityValidationError(
            f"Quantity for product {spec.name!r} must be positive, got {amount}",
        )

    if mode == QuantityInputMode.PACKAGE_COUNT:
        _validate_loading_packages(amount=amount, spec=spec)
        if max_packages is not None and amount > max_packages:
            raise QuantityValidationError(
                f"Packages quantity for product {spec.name!r} must be at most "
                f"{max_packages}, got {amount}",
            )
        if apply_stock_range and amount != 0:
            _validate_min_max_or_suspicious_unit_mismatch(amount=amount, spec=spec, mode=mode)
        return

    if mode == QuantityInputMode.BASE_STOCK:
        _validate_revision_stock(amount=amount, spec=spec)
        if apply_stock_range and amount != 0:
            _validate_min_max_or_suspicious_unit_mismatch(amount=amount, spec=spec, mode=mode)
        return

    raise QuantityValidationError(f"Unknown quantity mode: {mode!r}")


@beartype
def _require_pack_size(spec: ProductSpec, *, context: str) -> Decimal:
    pack_size = spec.pack_size
    if pack_size is None or pack_size <= 0:
        raise QuantityValidationError(
            f"Pack size must be configured for product {spec.name!r} {context}",
        )
    return pack_size


@beartype
def _validate_revision_stock(*, amount: Decimal, spec: ProductSpec) -> None:
    # For revision answers, input is already in base units (grams/ml/pieces).
    if spec.unit in {ProductUnit.GRAM, ProductUnit.KILOGRAM, ProductUnit.MILLILITER}:
        if not spec.allow_fraction and not _is_integral(amount):
            raise QuantityValidationError(
                f"Quantity for product {spec.name!r} must be an integer, got {amount}",
            )
        return

    if spec.unit == ProductUnit.PIECE:
        if not _is_integral(amount):
            raise QuantityValidationError(
                f"Quantity for product {spec.name!r} must be an integer, got {amount}",
            )
        return

    raise QuantityValidationError(f"Unsupported product unit for revision: {spec.unit!r}")


@beartype
def _validate_loading_packages(*, amount: Decimal, spec: ProductSpec) -> None:
    # For loading answers, input is always "packages".
    if not _is_integral(amount):
        raise QuantityValidationError(
            f"Packages quantity for product {spec.name!r} must be an integer, got {amount}",
        )

    _require_pack_size(spec, context="to validate loading")


@beartype
def _validate_min_max_or_suspicious_unit_mismatch(
    *,
    amount: Decimal,
    spec: ProductSpec,
    mode: QuantityInputMode,
) -> None:
    if spec.min_stock is None and spec.max_stock is None:
        return

    if mode == QuantityInputMode.PACKAGE_COUNT:
        pack_size = _require_pack_size(spec, context="to validate loading")
        base_correct = amount * pack_size
        if _in_range(base_correct, spec.min_stock, spec.max_stock):
            return

        base_alt = amount
        if _in_range(base_alt, spec.min_stock, spec.max_stock):
            packages_alt = base_alt / pack_size
            if _is_integral(packages_alt) and packages_alt > 0:
                raise SuspiciousUnitMismatchError(
                    f"Possible unit mix-up for {spec.name!r}: you entered {amount} as packages, "
                    f"but it fits as base quantity (expected packages ~ {packages_alt})",
                )

        unit_descr = "base units"
        raise QuantityValidationError(
            f"Quantity for product {spec.name!r} is out of range in base units: "
            f"got {base_correct} {unit_descr}, "
            f"expected between {spec.min_stock} and {spec.max_stock}",
        )

    if mode == QuantityInputMode.BASE_STOCK:
        if _in_range(amount, spec.min_stock, spec.max_stock):
            return

        pack_size = _require_pack_size(spec, context="for range validation")
        base_alt = amount * pack_size
        if _in_range(base_alt, spec.min_stock, spec.max_stock) and _is_integral(amount):
            raise SuspiciousUnitMismatchError(
                f"Possible unit mix-up for {spec.name!r}: you entered {amount} as base units, "
                f"but it fits as packages (expected base units ~ {base_alt})",
            )

        raise QuantityValidationError(
            f"Quantity for product {spec.name!r} is out of range: got {amount}, "
            f"expected between {spec.min_stock} and {spec.max_stock}",
        )

    raise QuantityValidationError(f"Unknown quantity mode: {mode!r}")


@beartype
def _in_range(value: Decimal, min_value: Decimal | None, max_value: Decimal | None) -> bool:
    if min_value is not None and value < min_value:
        return False
    return not (max_value is not None and value > max_value)


@beartype
def _is_integral(value: Decimal) -> bool:
    return value == value.to_integral_value()
