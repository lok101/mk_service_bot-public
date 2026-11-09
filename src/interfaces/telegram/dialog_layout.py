from __future__ import annotations

"""Вспомогательные константы layout текста aiogram-dialog.

Telegram подстраивает ширину bubble под самую короткую строку. На экранах с
короткими подписями (название аппарата, заголовок раздела) inline-клавиатура
визуально уже, чем на экранах с длинным текстом. Длинная первая строка фиксирует
ширину под клавиатуру.

Строка-заглушка видна пользователю (точки) — осознанный компромисс. Менять
``TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT`` только после проверки в клиенте Telegram.
Новые экраны с той же проблемой импортируют ``TELEGRAM_DIALOG_MIN_WIDTH_LINE``,
не копируют литерал.
"""

TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT = 106
TELEGRAM_DIALOG_MIN_WIDTH_LINE: str = "." * TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT
