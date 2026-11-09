from __future__ import annotations

import src.interfaces.google_forms.webhook as webhook_pkg


def test_webhook_package_public_surface() -> None:
    expected = {
        "build_google_forms_webhook_app",
        "GoogleFormsWebhookDeps",
        "DirectWarehouseChatNotifier",
        "WebhookTelegramBot",
        "NoOpDirectWarehouseChatNotifier",
        "WebhookPlaceholderBot",
    }
    assert set(webhook_pkg.__all__) == expected
    for name in expected:
        assert getattr(webhook_pkg, name) is not None
