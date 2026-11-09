from __future__ import annotations


def test_sales_monitoring_adapters_importable() -> None:
    from src.infrastructure.composition.wiring.sales_monitoring_worker_adapters import (
        MachineSalesForReportLoader,
        ReferenceDataTechnicianDisplayLookup,
        SyncOutboxHandlerDrainer,
    )

    assert MachineSalesForReportLoader is not None
    assert SyncOutboxHandlerDrainer is not None
    assert ReferenceDataTechnicianDisplayLookup is not None
