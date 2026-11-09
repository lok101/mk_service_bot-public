from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_review.ports import CatalogUnavailable
from src.domain.visit_photo_review import (
    CatalogInvalid,
    DefectButton,
    ReviewCatalog,
    parse_review_catalog,
)


@beartype
class FileReviewCatalog:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @beartype
    def load(self) -> ReviewCatalog:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogUnavailable(str(exc)) from exc
        try:
            return parse_review_catalog(payload)
        except CatalogInvalid as exc:
            raise CatalogUnavailable(str(exc)) from exc

    @beartype
    def replace_group_defects(
        self,
        group_id: str,
        defects: tuple[DefectButton, ...],
    ) -> None:
        catalog = self.load()
        groups_payload: list[dict[str, object]] = []
        found = False
        for group in catalog.groups:
            if group.group_id == group_id:
                found = True
                groups_payload.append(
                    {
                        "group_id": group.group_id,
                        "title": group.title,
                        "required": group.required,
                        "defects": [{"code": item.code, "label": item.label} for item in defects],
                    }
                )
            else:
                groups_payload.append(
                    {
                        "group_id": group.group_id,
                        "title": group.title,
                        "required": group.required,
                        "defects": [
                            {"code": item.code, "label": item.label} for item in group.defects
                        ],
                    }
                )
        if not found:
            raise CatalogUnavailable(f"group not found: {group_id}")
        self._atomic_write({"groups": groups_payload})

    def _atomic_write(self, payload: dict[str, object]) -> None:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
            tmp_name = None
        except OSError as exc:
            raise CatalogUnavailable(str(exc)) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if tmp_name is not None and os.path.exists(tmp_name):
                os.unlink(tmp_name)
