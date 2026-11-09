from __future__ import annotations

from dataclasses import dataclass

from src.application.photo_integrity.ports import PhotoIntegrityAlertNotifier


@dataclass(slots=True)
class PhotoIntegrityAlertNotifierRef:
    notifier: PhotoIntegrityAlertNotifier
