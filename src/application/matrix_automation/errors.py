from __future__ import annotations


class MatrixReferenceParseError(Exception):
    """Global abort during matrix reference data parse."""


class BaseMarginParseError(MatrixReferenceParseError):
    pass


class ProductMultipliersParseError(MatrixReferenceParseError):
    pass


class PurchasePricesBatchError(Exception):
    pass
