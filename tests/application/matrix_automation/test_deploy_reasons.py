from __future__ import annotations

from src.application.matrix_automation import BASELINE_ALREADY_PRESENT as EXPORTED
from src.application.matrix_automation.deploy_reasons import BASELINE_ALREADY_PRESENT


def test_baseline_already_present_constant_value() -> None:
    assert BASELINE_ALREADY_PRESENT == "baseline_already_present"
    assert EXPORTED == "baseline_already_present"
