from __future__ import annotations


class SaleProductCodeResolveError(Exception):
    """Не удалось определить код товара для разрешённой продажи."""


class SaleProductCodeResolveCriticalError(SaleProductCodeResolveError):
    """Несогласованные или неполные данные каталога/матрицы — логируется как warning."""


class SaleProductCodeResolveNonCriticalError(SaleProductCodeResolveError):
    """Ожидаемый пропуск (переплата, «Товар 0», не плейсхолдер и т. п.) — логируется как debug."""
