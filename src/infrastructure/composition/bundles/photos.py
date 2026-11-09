from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_batches.ports import PhotoBatchStore, PhotoStorage
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef


@beartype
@dataclass(frozen=True, slots=True)
class PhotoPipelineBundle:
    batch_store: PhotoBatchStore
    storage: PhotoStorage
    accept_loading_photos: AcceptLoadingPhotosService
    downloader_ref: PhotoDownloaderRef
    loading_photos_notifier_ref: LoadingPhotosChatNotifierRef
    integrity_alert_notifier_ref: PhotoIntegrityAlertNotifierRef
    form_workflow_notifier_ref: FormWorkflowNotifierRef
