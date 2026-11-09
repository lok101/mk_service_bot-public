from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow import (
    FormWorkflowAccepted,
    FormWorkflowIntegrationFailed,
    FormWorkflowInvalid,
    FormWorkflowNotifier,
    FormWorkflowOutcome,
    FormWorkflowRejected,
    resolve_navigation,
    utc_now,
)
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.telegram.contracts import TelegramDialogBackgroundFactory
from src.interfaces.telegram.form_workflow import FormWorkflowSession
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.form_workflow_dialog import refresh_workspace_panel
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.form_workflow_error import format_form_error_block

logger = logging.getLogger(__name__)

_PURPOSE_LABELS: dict[FormSubmissionPurpose, str] = {
    "revision": "инвентаризация",
    "loading": "загрузка",
}


@beartype
@dataclass(frozen=True, slots=True)
class TelegramFormWorkflowNotifier(FormWorkflowNotifier):
    bot: Bot
    session_store: FormWorkflowSessionStore
    telegram_user_resolver: TelegramUserResolver
    dialog_bg_factory: TelegramDialogBackgroundFactory
    machine_list_deps: MachineListDeps

    @beartype
    async def notify(self, outcome: FormWorkflowOutcome) -> None:
        enriched = _enrich_outcome(outcome, self.session_store)
        navigation = resolve_navigation(enriched)
        session = _find_session(enriched, self.session_store)
        chat_id = _resolve_chat_id(session, enriched, self.telegram_user_resolver)
        if chat_id is None:
            logger.info(
                "Form workflow notify skipped: no Telegram chat for outcome %s",
                type(outcome).__name__,
            )
            return

        form_error = _form_error_detail(enriched) if navigation.form_error_in_window else None

        if navigation.notify_in_chat:
            text = _format_message(enriched, navigation.message_heading)
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                logger.exception("Failed to send form workflow message to chat %s", chat_id)

        nav_session = session or _fallback_session_for_navigation(
            enriched,
            chat_id=chat_id,
            telegram_user_resolver=self.telegram_user_resolver,
            form_error_in_window=navigation.form_error_in_window,
        )
        if nav_session is not None:
            refresh_links = isinstance(enriched, FormWorkflowAccepted)
            updated = await self._refresh_workspace(
                nav_session,
                form_error=form_error,
                refresh_links=refresh_links,
            )
            if not updated and form_error is not None and navigation.form_error_in_window:
                await self._send_form_error_fallback(chat_id, form_error)
        elif navigation.form_error_in_window:
            logger.warning(
                "Form workflow in-window update skipped: no session for purpose=%s",
                _outcome_correlation(enriched)[2],
            )
            if form_error is not None:
                await self._send_form_error_fallback(chat_id, form_error)
        elif form_error is not None and navigation.notify_in_chat:
            text = _format_form_error_chat_message(form_error)
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                logger.exception("Failed to send form workflow message to chat %s", chat_id)

        if navigation.clear_session:
            _clear_session(enriched, self.session_store)

    @beartype
    async def _refresh_workspace(
        self,
        session: FormWorkflowSession,
        *,
        form_error: str | None,
        refresh_links: bool,
    ) -> bool:
        bg_manager = self.dialog_bg_factory.bg(
            bot=self.bot,
            user_id=session.telegram_user_id,
            chat_id=session.chat_id,
            load=True,
        )
        try:
            return await refresh_workspace_panel(
                bg_manager,
                self.machine_list_deps,
                session=session,
                form_error=form_error,
                refresh_links=refresh_links,
            )
        except Exception:
            logger.exception(
                "Failed to refresh workspace panel for chat %s",
                session.chat_id,
            )
            return False

    @beartype
    async def _send_form_error_fallback(self, chat_id: int, detail: str) -> None:
        text = format_form_error_block(detail)
        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "Failed to send form workflow fallback message to chat %s",
                chat_id,
            )


@beartype
@dataclass(frozen=True, slots=True)
class NoOpFormWorkflowNotifier(FormWorkflowNotifier):
    @beartype
    async def notify(self, outcome: FormWorkflowOutcome) -> None:
        _ = outcome


@beartype
def _enrich_outcome(
    outcome: FormWorkflowOutcome,
    session_store: FormWorkflowSessionStore,
) -> FormWorkflowOutcome:
    session = _find_session(outcome, session_store)
    if session is None:
        return outcome

    maintenance_screen = session.maintenance_screen
    if isinstance(outcome, FormWorkflowAccepted):
        return FormWorkflowAccepted(
            technician_id=outcome.technician_id,
            machine_id=outcome.machine_id,
            purpose=outcome.purpose,
            maintenance_screen=maintenance_screen,
            detail=outcome.detail,
        )
    if isinstance(outcome, FormWorkflowRejected):
        return FormWorkflowRejected(
            technician_id=outcome.technician_id,
            machine_id=outcome.machine_id,
            purpose=outcome.purpose,
            detail=outcome.detail,
            maintenance_screen=maintenance_screen,
        )
    if isinstance(outcome, FormWorkflowInvalid):
        return FormWorkflowInvalid(
            technician_id=outcome.technician_id or session.technician_id,
            machine_id=outcome.machine_id or session.machine_id,
            purpose=outcome.purpose or session.purpose,
            detail=outcome.detail,
            maintenance_screen=maintenance_screen,
        )
    if isinstance(outcome, FormWorkflowIntegrationFailed):
        return FormWorkflowIntegrationFailed(
            technician_id=outcome.technician_id,
            machine_id=outcome.machine_id,
            purpose=outcome.purpose,
            detail=outcome.detail,
            maintenance_screen=maintenance_screen,
        )
    return outcome


@beartype
def _find_session(
    outcome: FormWorkflowOutcome,
    session_store: FormWorkflowSessionStore,
) -> FormWorkflowSession | None:
    technician_id, machine_id, purpose = _outcome_correlation(outcome)
    if technician_id is None or machine_id is None or purpose is None:
        return None
    return session_store.find(technician_id, machine_id, purpose)


@beartype
def _outcome_correlation(
    outcome: FormWorkflowOutcome,
) -> tuple[TechnicianId | None, MachineId | None, FormSubmissionPurpose | None]:
    if isinstance(outcome, FormWorkflowAccepted):
        return outcome.technician_id, outcome.machine_id, outcome.purpose
    if isinstance(outcome, FormWorkflowRejected):
        return outcome.technician_id, outcome.machine_id, outcome.purpose
    if isinstance(outcome, FormWorkflowInvalid):
        return outcome.technician_id, outcome.machine_id, outcome.purpose
    if isinstance(outcome, FormWorkflowIntegrationFailed):
        return outcome.technician_id, outcome.machine_id, outcome.purpose
    return None, None, None


@beartype
def _resolve_chat_id(
    session: FormWorkflowSession | None,
    outcome: FormWorkflowOutcome,
    telegram_user_resolver: TelegramUserResolver,
) -> int | None:
    if session is not None:
        return session.chat_id

    technician_id, _, _ = _outcome_correlation(outcome)
    if technician_id is None:
        return None

    bot_user = telegram_user_resolver.find_by_technician_id(technician_id)
    if bot_user is None:
        logger.warning(
            "Cannot notify technician %s: Telegram user was not found",
            technician_id.value,
        )
        return None
    return bot_user.telegram_user_id


@beartype
def _fallback_session_for_navigation(
    outcome: FormWorkflowOutcome,
    *,
    chat_id: int,
    telegram_user_resolver: TelegramUserResolver,
    form_error_in_window: bool,
) -> FormWorkflowSession | None:
    if not form_error_in_window:
        return None

    technician_id, machine_id, purpose = _outcome_correlation(outcome)
    if technician_id is None or machine_id is None or purpose is None:
        return None

    bot_user = telegram_user_resolver.find_by_technician_id(technician_id)
    if bot_user is None:
        return None

    maintenance_screen = "maintenance"
    if isinstance(
        outcome,
        (
            FormWorkflowAccepted,
            FormWorkflowRejected,
            FormWorkflowInvalid,
            FormWorkflowIntegrationFailed,
        ),
    ):
        maintenance_screen = outcome.maintenance_screen

    return FormWorkflowSession(
        chat_id=chat_id,
        telegram_user_id=bot_user.telegram_user_id,
        technician_id=technician_id,
        machine_id=machine_id,
        machine_name=machine_id.value,
        purpose=purpose,
        maintenance_screen=maintenance_screen,
        registered_at=utc_now(),
    )


@beartype
def _clear_session(
    outcome: FormWorkflowOutcome,
    session_store: FormWorkflowSessionStore,
) -> None:
    technician_id, machine_id, purpose = _outcome_correlation(outcome)
    if technician_id is None or machine_id is None or purpose is None:
        return
    session_store.remove(technician_id, machine_id, purpose)


@beartype
def _form_error_detail(outcome: FormWorkflowOutcome) -> str | None:
    if isinstance(
        outcome,
        (FormWorkflowInvalid, FormWorkflowRejected, FormWorkflowIntegrationFailed),
    ):
        return outcome.detail
    return None


@beartype
def _format_form_error_chat_message(detail: str) -> str:
    return f"🔴 Ошибка формы\n\n{detail.strip()}"


@beartype
def _format_message(outcome: FormWorkflowOutcome, heading: str) -> str:
    purpose = _outcome_correlation(outcome)[2]
    purpose_label = _PURPOSE_LABELS.get(purpose, "форма") if purpose else "форма"
    machine_id = _outcome_correlation(outcome)[1]
    machine_suffix = f", аппарат {machine_id.value}" if machine_id is not None else ""

    detail = ""
    if isinstance(
        outcome,
        (
            FormWorkflowAccepted,
            FormWorkflowRejected,
            FormWorkflowInvalid,
            FormWorkflowIntegrationFailed,
        ),
    ):
        detail = outcome.detail

    if detail:
        return f"{heading} ({purpose_label}{machine_suffix}).\n{detail}"
    return f"{heading} ({purpose_label}{machine_suffix})."
