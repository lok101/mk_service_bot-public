from __future__ import annotations

from beartype import beartype

from src.application.form_submissions.ports import FormSubmissionStore
from src.application.form_workflow import FormWorkflowNotifier
from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    ShopListPublishJournal,
)
from src.application.outbox.composite_terminal_failure_notifier import (
    CompositeOutboxTerminalFailureNotifier,
)
from src.application.outbox.ports import OutboxEventDeserializer, OutboxTerminalFailureNotify
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.config.settings import Settings
from src.infrastructure.composition.adapters.daily_sales_demand_ops_alerter import (
    build_daily_sales_demand_ops_alerter,
)
from src.infrastructure.composition.adapters.machine_pnl_ops_alerter import (
    build_machine_pnl_ops_alerter,
)
from src.infrastructure.composition.adapters.shop_list_publish_terminal import (
    ShopListPublishTerminalNotifier,
)


@beartype
def build_outbox_failure_notifier(
    settings: Settings,
    *,
    form_submission_store: FormSubmissionStore,
    form_workflow_notifier: FormWorkflowNotifier,
    event_deserializer: OutboxEventDeserializer,
    planogram_store: MicromarketPlanogramStore | None = None,
    shop_list_publish_journal: ShopListPublishJournal | None = None,
) -> OutboxTerminalFailureNotify:
    composite: OutboxTerminalFailureNotify = CompositeOutboxTerminalFailureNotifier(
        primary=OutboxTerminalFailureNotifier(
            form_submission_store=form_submission_store,
            form_workflow_notifier=form_workflow_notifier,
            event_deserializer=event_deserializer,
        ),
        machine_pnl_ops=build_machine_pnl_ops_alerter(settings),
        daily_sales_demand_ops=build_daily_sales_demand_ops_alerter(settings),
        event_deserializer=event_deserializer,
    )
    if planogram_store is None:
        return composite
    return ShopListPublishTerminalNotifier(
        inner=composite,
        store=planogram_store,
        journal=shop_list_publish_journal,
    )
