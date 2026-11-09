from __future__ import annotations

from scripts.agent_process_report_lib.redaction import redact_text


def test_redaction_strips_secrets_and_limits_error_text() -> None:
    raw = (
        "failed token=super-secret-value-here "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig "
        "api_key=ABCDEF0123456789 " + ("x" * 500)
    )
    redacted = redact_text(raw, max_len=120)
    assert "super-secret-value-here" not in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "ABCDEF0123456789" not in redacted
    assert "[REDACTED]" in redacted
    assert len(redacted) <= 120
