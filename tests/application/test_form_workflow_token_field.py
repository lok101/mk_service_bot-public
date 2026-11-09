from __future__ import annotations

from src.application.form_workflow.token_field import (
    find_form_token_in_answers,
    form_token_answer_mismatch_message,
    format_form_token_field_error,
)
from src.domain.form_submission import FormAnswer


def test_format_form_token_field_error_signature_invalid() -> None:
    message = format_form_token_field_error(
        "Revision form token signature is invalid",
        "Код заявки.",
    )
    assert "Код заявки." in message
    assert "изменили" in message.lower() or "вручную" in message.lower()
    assert "бот" in message.lower()


def test_format_form_token_field_error_expired() -> None:
    message = format_form_token_field_error(
        "Revision form token has expired",
        "Код заявки.",
    )
    assert "устарел" in message
    assert "Код заявки." in message


def test_form_token_answer_mismatch_message() -> None:
    message = form_token_answer_mismatch_message("Код заявки.")
    assert "не совпадает" in message
    assert "Код заявки." in message


def test_find_form_token_in_answers() -> None:
    answers = (
        FormAnswer(title="Код заявки.", value="  token-value  "),
        FormAnswer(title="Кофе", value="1"),
    )
    assert find_form_token_in_answers(answers, "Код заявки.") == "token-value"
