from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs


@beartype
@dataclass(slots=True)
class InMemorySettlementAnalysisPrefsStore:
    _by_telegram_id: dict[int, SettlementAnalysisPrefs] = field(default_factory=dict)

    def get(self, telegram_user_id: int) -> SettlementAnalysisPrefs:
        prefs = self._by_telegram_id.get(telegram_user_id)
        if prefs is None:
            return SettlementAnalysisPrefs.empty()
        return prefs

    def save(self, telegram_user_id: int, prefs: SettlementAnalysisPrefs) -> None:
        self._by_telegram_id[telegram_user_id] = prefs
