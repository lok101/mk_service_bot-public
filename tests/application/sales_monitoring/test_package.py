from __future__ import annotations


def test_sales_monitoring_package_importable() -> None:
    import src.application.sales_monitoring as sm

    for name in (
        "parse_excluded_machine_codes",
        "detect_sales_findings",
        "decide_offline_lifecycle",
        "MachineOfflineInput",
        "OfflineLifecycleDecision",
    ):
        assert name in sm.__all__
    assert callable(sm.parse_excluded_machine_codes)
    assert callable(sm.detect_sales_findings)
    assert callable(sm.decide_offline_lifecycle)
