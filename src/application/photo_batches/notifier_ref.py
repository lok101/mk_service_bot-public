from __future__ import annotations

from dataclasses import dataclass

from src.application.photo_batches.notifier_ports import LoadingPhotosChatNotifier


@dataclass(slots=True)
class LoadingPhotosChatNotifierRef:
    notifier: LoadingPhotosChatNotifier
