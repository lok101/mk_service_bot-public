from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.visit_photo_review.fakes import (
    FixedBatches,
    FixedCatalog,
    FixedClock,
    MemoryGroupAvatarWriter,
    MemoryReviewStore,
)

from src.application.master_data import (
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SaveSystemUsers,
    SystemUserRecord,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.application.visit_photo_grouping import DisposeUnrecognizedIndex
from src.application.visit_photo_review import (
    ClearReviewRecord,
    RecordMissingRequiredGroup,
    RelocateBatchIndex,
    ReviewQueries,
    SaveReviewRecord,
    UpdateGroupDefects,
    WriteGroupAvatar,
)
from src.application.visit_photo_review.ports import (
    AcceptedBatch,
    AcceptedPhotoFile,
    ReviewLabelLookup,
)
from src.domain.calendar import operational_day
from src.domain.system_user import AdminPanel, BotRole, CompanyRole, SystemUser, SystemUserId
from src.domain.visit_photo_review import (
    CatalogGroup,
    DefectButton,
    DefectMark,
    FrameView,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)
from src.infrastructure.photo_batches.stubs import InMemoryPhotoStorage
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
_TZ = ZoneInfo("Europe/Moscow")
_DAY_END = 6
_BATCH = "batch-1"
_GROUP = "waste_tank"
_UNRECOGNIZED = "unrecognized"
_POOR_QUALITY = "poor_quality"
_CUP = "cup"


def test_visit_photo_review_nav_label() -> None:
    from src.interfaces.admin.system_users_view import _PANEL_NAV

    row = next(item for item in _PANEL_NAV if item[0] is AdminPanel.VISIT_PHOTO_REVIEW)
    assert row[1:] == (
        "/admin/visit-photo-review",
        "Разбор фото",
        "admin-icon-visit-photo-review",
    )


def test_visit_photo_review_derived_from_access_administrator() -> None:
    from src.domain.system_user import panels_for_roles

    assert AdminPanel.VISIT_PHOTO_REVIEW in panels_for_roles({CompanyRole.ACCESS_ADMINISTRATOR})


def _system_user(*, tg: int, panels: frozenset[AdminPanel]) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId(str(tg)),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=tg,
        technician_id=None,
        company_roles=company_roles_for_test_panels(panels),
    )


def _catalog(*, unavailable: bool = False) -> FixedCatalog:
    return FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id=_GROUP,
                    title="Бак отходов",
                    required=True,
                    defects=(DefectButton(code="dirty", label="Грязь"),),
                ),
            )
        ),
        unavailable=unavailable,
    )


def _catalog_with_reserved(*, unavailable: bool = False) -> FixedCatalog:
    return FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id=_GROUP,
                    title="Бак отходов",
                    required=True,
                    defects=(DefectButton(code="dirty", label="Грязь"),),
                ),
                CatalogGroup(
                    group_id=_CUP,
                    title="Стакан",
                    required=False,
                    defects=(),
                ),
                CatalogGroup(
                    group_id=_UNRECOGNIZED,
                    title="Не удалось определить",
                    required=False,
                    defects=(),
                ),
                CatalogGroup(
                    group_id=_POOR_QUALITY,
                    title="Некачественные фото",
                    required=False,
                    defects=(),
                ),
            )
        ),
        unavailable=unavailable,
    )


def _accepted_batch(*, indexes: tuple[int, ...] = (0, 1)) -> AcceptedBatch:
    return AcceptedBatch(
        batch_id=_BATCH,
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_FROZEN_NOW,
        files=tuple(
            AcceptedPhotoFile(
                index=index,
                content_type="image/jpeg",
                storage_key=f"k-{index}",
            )
            for index in indexes
        ),
    )


def _seed_assignment(store: MemoryReviewStore, *, indexes: tuple[int, ...] = (0, 1)) -> None:
    store.replace_assignments(
        _BATCH,
        (
            GroupAssignment(
                batch_id=_BATCH,
                group_id=_GROUP,
                indexes=indexes,
                machine_id="m-1",
                technician_id="t-1",
                occurred_at=_FROZEN_NOW,
            ),
        ),
        clear_missing_group_ids=(),
    )


def _seed_unrecognized(
    store: MemoryReviewStore,
    *,
    indexes: tuple[int, ...] = (0, 1),
    neighbors: tuple[tuple[str, tuple[int, ...]], ...] = (),
) -> None:
    assignments = [
        GroupAssignment(
            batch_id=_BATCH,
            group_id=group_id,
            indexes=group_indexes,
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
        for group_id, group_indexes in neighbors
    ]
    assignments.append(
        GroupAssignment(
            batch_id=_BATCH,
            group_id=_UNRECOGNIZED,
            indexes=indexes,
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )
    store.replace_assignments(_BATCH, tuple(assignments), clear_missing_group_ids=())


_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg-payload"
_TRASH = "trash"


def _build_app(
    *,
    enabled: bool = True,
    visit_photo_review_enabled: bool = True,
    users_enabled: bool = True,
    panels: frozenset[AdminPanel] | None = None,
    telegram_user_id: int = _ADMIN_TG,
    store: MemoryReviewStore | None = None,
    catalog: FixedCatalog | None = None,
    photo_storage: InMemoryPhotoStorage | None = None,
    batch: AcceptedBatch | None = None,
    review_label_lookup: ReviewLabelLookup | None = None,
    wire_dispose: bool = False,
    wire_group_editor: bool = False,
    avatar_store: MemoryGroupAvatarWriter | None = None,
) -> tuple[FastAPI, AdminHttpDeps, MemoryReviewStore, InMemoryPhotoStorage]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)

    effective_panels = (
        panels
        if panels is not None
        else frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_PHOTO_REVIEW})
    )
    user = _system_user(tg=telegram_user_id, panels=effective_panels)
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={telegram_user_id: user},
            users_by_technician_id={},
        ),
    )

    review_store = store if store is not None else MemoryReviewStore()
    review_catalog = catalog if catalog is not None else _catalog()
    accepted = batch if batch is not None else _accepted_batch()
    batches = FixedBatches(accepted)
    queries = ReviewQueries(review_catalog, review_store, batches)
    clock = FixedClock(_FROZEN_NOW)
    save = SaveReviewRecord(catalog=review_catalog, store=review_store, clock=clock.now)
    clear = ClearReviewRecord(store=review_store)
    dispose = None
    if wire_dispose and visit_photo_review_enabled:
        missing = RecordMissingRequiredGroup(
            catalog=review_catalog,
            store=review_store,
            batches=batches,
            clock=clock.now,
        )
        dispose = DisposeUnrecognizedIndex(
            catalog=review_catalog,
            store=review_store,
            batches=batches,
            relocate=RelocateBatchIndex(review_catalog, review_store, batches),
            missing=missing,
        )
    storage = photo_storage if photo_storage is not None else InMemoryPhotoStorage()
    avatars = avatar_store if avatar_store is not None else MemoryGroupAvatarWriter()
    update_group_defects = None
    write_group_avatar = None
    group_avatar_reader = None
    if wire_group_editor and visit_photo_review_enabled:
        update_group_defects = UpdateGroupDefects(review_catalog)
        write_group_avatar = WriteGroupAvatar(avatars)
        group_avatar_reader = avatars

    system_user_store = None
    save_system_users = None
    if users_enabled:
        system_user_store = InMemorySystemUserStore()
        system_user_store.replace_all(
            (
                SystemUserRecord(
                    user=user,
                    updated_at=_FROZEN_NOW,
                    updated_by_telegram_user_id=telegram_user_id,
                ),
            ),
        )
        save_system_users = SaveSystemUsers(
            store=system_user_store,
            counters=InMemoryMasterDataCounterStore(),
        )

    deps = AdminHttpDeps(
        provider=provider,
        roster_store=roster_store,
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token=_BOT_TOKEN,
        session_secret=_SESSION_SECRET,
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=True,
        timezone=_TZ,
        day_end_hour=_DAY_END,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=InMemoryMasterDataStores(),
        users_enabled=users_enabled,
        system_user_store=system_user_store,
        save_system_users=save_system_users,
        visit_photo_review_enabled=visit_photo_review_enabled,
        review_queries=queries if visit_photo_review_enabled else None,
        save_review_record=save if visit_photo_review_enabled else None,
        clear_review_record=clear if visit_photo_review_enabled else None,
        dispose_unrecognized_index=dispose,
        photo_storage=storage if visit_photo_review_enabled else None,
        review_label_lookup=review_label_lookup,
        group_avatar_reader=group_avatar_reader,
        update_group_defects=update_group_defects,
        write_group_avatar=write_group_avatar,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps, review_store, storage


def _login(client: TestClient, *, tg: int = _ADMIN_TG) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(tg)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def test_visit_photo_review_list_offloads_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-photo-review?day=all")
    assert response.status_code == 200
    assert calls, "GET list must call asyncio.to_thread"


def test_visit_photo_review_route_missing_when_flag_off() -> None:
    app, _deps, _store, _storage = _build_app(visit_photo_review_enabled=False)
    client = TestClient(app)
    _login(client)
    assert client.get("/admin/visit-photo-review").status_code == 404


def test_visit_photo_review_forbidden_without_panel() -> None:
    app, _deps, _store, _storage = _build_app(
        panels=frozenset({AdminPanel.ROSTER}),
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/visit-photo-review").status_code == 403
    assert client.get(f"/admin/visit-photo-review/photos/{_BATCH}/0").status_code == 403
    assert client.get(f"/admin/visit-photo-review/avatars/{_GROUP}").status_code == 403
    assert (
        client.post(
            f"/admin/visit-photo-review/frames/{_BATCH}/0/view",
            headers={"origin": "http://testserver"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
            data={"defect_code": "dirty"},
            headers={"origin": "http://testserver"},
        ).status_code
        == 403
    )


def test_queue_mutating_routes_forbidden_bad_origin() -> None:
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    evil = {"origin": "https://evil.example"}
    assert (
        client.get(f"/admin/visit-photo-review/avatars/{_GROUP}", headers=evil).status_code == 403
    )
    assert (
        client.post(
            f"/admin/visit-photo-review/frames/{_BATCH}/0/view",
            headers=evil,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
            data={"defect_code": "dirty"},
            headers=evil,
        ).status_code
        == 403
    )


def test_avatar_route_traversal_returns_404(tmp_path: Path) -> None:
    from src.infrastructure.visit_photo_review.group_avatar import PackDirGroupAvatarReader

    group_dir = tmp_path / "reference" / _GROUP
    group_dir.mkdir(parents=True)
    (group_dir / "a.jpg").write_bytes(b"jpg")
    app, deps, _store, _storage = _build_app()
    object.__setattr__(deps, "group_avatar_reader", PackDirGroupAvatarReader(tmp_path))
    client = TestClient(app)
    _login(client)
    headers = {"origin": "http://testserver"}
    assert (
        client.get("/admin/visit-photo-review/avatars/../secret", headers=headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/admin/visit-photo-review/avatars/{_GROUP}%2F..%2Fsecret",
            headers=headers,
        ).status_code
        == 404
    )


def test_avatar_route_happy_when_reader_wired(tmp_path: Path) -> None:
    from src.infrastructure.visit_photo_review.group_avatar import PackDirGroupAvatarReader

    group_dir = tmp_path / "reference" / _GROUP
    group_dir.mkdir(parents=True)
    (group_dir / "a.jpg").write_bytes(b"jpg-bytes")
    app, deps, _store, _storage = _build_app()
    object.__setattr__(deps, "group_avatar_reader", PackDirGroupAvatarReader(tmp_path))
    client = TestClient(app)
    _login(client)
    response = client.get(
        f"/admin/visit-photo-review/avatars/{_GROUP}",
        headers={"origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.content == b"jpg-bytes"
    assert response.headers["content-type"].startswith("image/jpeg")


def test_list_without_day_redirects_to_operational_day() -> None:
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-photo-review", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    expected_day = operational_day(_FROZEN_NOW, _TZ, _DAY_END)
    assert f"day={expected_day.isoformat()}" in location


def test_day_all_does_not_apply_day_filter() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, deps, _store, _storage = _build_app(store=store)
    assert deps.review_queries is not None
    calls: list[object] = []
    real = deps.review_queries.list_queue_groups

    def tracking(**kwargs: object) -> object:
        calls.append(kwargs.get("day"))
        return real(**kwargs)  # type: ignore[arg-type]

    object.__setattr__(deps.review_queries, "list_queue_groups", tracking)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-photo-review?day=all")
    assert response.status_code == 200
    assert calls == [None]


def test_block_page_has_no_save_bar() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    html = client.get(f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}").text
    assert "admin-save-bar" not in html


def test_close_with_mark_saves_record() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-dirty": "on", "comment": "ok", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    record = store.find_frame_record(_BATCH, _GROUP, 0)
    assert record is not None
    assert record.defects[0].code == "dirty"


def test_comment_without_marks_does_not_create_record() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"comment": "only comment", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert store.find_frame_record(_BATCH, _GROUP, 0) is None


def test_closing_without_marks_clears_existing_record() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    store.save_record(
        ReviewRecord(
            batch_id=_BATCH,
            group_id=_GROUP,
            record_kind="human",
            indexes=(0,),
            defects=(DefectMark(code="dirty", label="Грязь"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="1001",
            saved_at=_FROZEN_NOW,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"comment": "", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert store.find_frame_record(_BATCH, _GROUP, 0) is None


def test_block_form_without_frame_index_rejected() -> None:
    # error — same index requirement as /mark
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-dirty": "on"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert store.find_frame_record(_BATCH, _GROUP, 0) is None


def test_save_without_assignment_is_409() -> None:
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-dirty": "on", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 409


def test_unknown_defect_is_422() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-unknown": "on", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 422


def test_catalog_unavailable_is_503() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store, catalog=_catalog(unavailable=True))
    client = TestClient(app)
    _login(client)
    assert client.get("/admin/visit-photo-review?day=all").status_code == 503
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-dirty": "on", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 503


def test_second_save_keeps_last_actor() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"defect-dirty": "on", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    other = 2002
    provider_user = _system_user(
        tg=other,
        panels=frozenset({AdminPanel.VISIT_PHOTO_REVIEW}),
    )
    _deps.provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                _ADMIN_TG: _system_user(
                    tg=_ADMIN_TG,
                    panels=frozenset({AdminPanel.VISIT_PHOTO_REVIEW}),
                ),
                other: provider_user,
            },
            users_by_technician_id={},
        ),
    )
    if _deps.system_user_store is not None:
        _deps.system_user_store.replace_all(
            (
                SystemUserRecord(
                    user=_system_user(
                        tg=_ADMIN_TG,
                        panels=frozenset({AdminPanel.VISIT_PHOTO_REVIEW}),
                    ),
                    updated_at=_FROZEN_NOW,
                    updated_by_telegram_user_id=_ADMIN_TG,
                ),
                SystemUserRecord(
                    user=provider_user,
                    updated_at=_FROZEN_NOW,
                    updated_by_telegram_user_id=_ADMIN_TG,
                ),
            ),
        )
    client2 = TestClient(app)
    _login(client2, tg=other)
    client2.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}",
        data={"system_error": "on", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    record = store.find_frame_record(_BATCH, _GROUP, 0)
    assert record is not None
    assert record.actor_user_id == str(other)


def test_photo_bytes_404_when_index_not_in_assignment_or_record() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0,))
    app, _deps, _store, storage = _build_app(store=store, batch=_accepted_batch(indexes=(0,)))
    storage._objects["k-0"] = b"jpeg-0"
    storage._objects["k-9"] = b"jpeg-9"
    client = TestClient(app)
    _login(client)
    assert client.get(f"/admin/visit-photo-review/photos/{_BATCH}/9").status_code == 404


def test_photo_bytes_returns_content_type() -> None:
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0,))
    storage = InMemoryPhotoStorage()
    storage._objects["k-0"] = b"jpeg-bytes"
    app, _deps, review_store, _storage = _build_app(
        store=store,
        photo_storage=storage,
        batch=_accepted_batch(indexes=(0,)),
    )
    client = TestClient(app)
    _login(client)
    response = client.get(f"/admin/visit-photo-review/photos/{_BATCH}/0")
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-type"].startswith("image/jpeg")
    assert review_store.find_record(_BATCH, _GROUP) is None

    class _FailStorage:
        async def save(self, **_kwargs: object) -> str:
            raise AssertionError("save not used")

        async def get_bytes(self, storage_key: str) -> bytes:
            raise ValueError(f"missing {storage_key}")

        async def delete(self, storage_key: str) -> None:
            return None

    from dataclasses import replace

    deps_fail = replace(_deps, photo_storage=_FailStorage())  # type: ignore[arg-type]
    app_fail = FastAPI()
    register_admin_routes(app_fail, deps_fail, enabled=True)
    client_fail = TestClient(app_fail)
    _login(client_fail)
    assert client_fail.get(f"/admin/visit-photo-review/photos/{_BATCH}/0").status_code == 404
    assert review_store.find_record(_BATCH, _GROUP) is None


def test_history_route_returns_404() -> None:
    # happy — ISS-020
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    assert client.get("/admin/visit-photo-review/history?day=all").status_code == 404


def test_history_source_deep_link_not_special_cased() -> None:
    # edge — source=history no longer switches indexes to saved record
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0,))
    store.save_record(
        ReviewRecord(
            batch_id=_BATCH,
            group_id=_GROUP,
            record_kind="human",
            indexes=(1,),
            defects=(DefectMark(code="dirty", label="Грязь"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="1001",
            saved_at=_FROZEN_NOW,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )
    app, _deps, _store, _storage = _build_app(
        store=store,
        batch=_accepted_batch(indexes=(0, 1)),
    )
    client = TestClient(app)
    _login(client)
    block = client.get(f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}?day=all&source=history")
    assert block.status_code == 200
    assert f"/admin/visit-photo-review/photos/{_BATCH}/0" in block.text


def test_block_template_does_not_fetch_on_toggle() -> None:
    template = Path("src/interfaces/admin/templates/visit_photo_review_block.html")
    text = template.read_text(encoding="utf-8")
    assert "fetch(" not in text


def test_dispose_post_with_panel_redirects_303() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0, 1))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose?day=all",
        data={"index": "0", "action": "content", "target_group_id": _CUP},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized" in location
    assert "day=all" in location
    remaining = store.find_assignment(_BATCH, _UNRECOGNIZED)
    assert remaining is not None
    assert remaining.indexes == (1,)


def test_dispose_accept_json_returns_ok_without_redirect() -> None:
    # happy — carousel stays on list; must not 303 to old block page
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0, 1))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose?day=all",
        data={"index": "0", "action": "content", "target_group_id": _CUP},
        headers={
            "origin": "http://testserver",
            "accept": "application/json",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "location" not in response.headers
    payload = response.json()
    assert payload["ok"] is True
    assert payload["remaining_indexes"] == [1]
    remaining = store.find_assignment(_BATCH, _UNRECOGNIZED)
    assert remaining is not None
    assert remaining.indexes == (1,)


def test_dispose_accept_json_reject_surfaces_message() -> None:
    # error
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,), neighbors=((_CUP, (1,)),))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        batch=_accepted_batch(indexes=(0, 1)),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose",
        data={"index": "1", "action": "content", "target_group_id": _GROUP},
        headers={
            "origin": "http://testserver",
            "accept": "application/json",
        },
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert response.json()["error"]


def test_carousel_js_intercepts_dispose_submit() -> None:
    # edge — native form POST would leave carousel for old block page
    text = Path("src/interfaces/admin/static/visit_photo_review_queue.js").read_text(
        encoding="utf-8"
    )
    assert "disposeForm" in text
    assert 'Accept: "application/json"' in text or "application/json" in text
    assert "preventDefault" in text
    assert "disposeContentActions" in text
    assert "dataset.targetGroupId" in text
    assert "syncDisposeButtons" not in text
    # name="action" buttons shadow HTMLFormElement.action → use attribute API
    assert (
        'setAttribute(\n      "action"' in text
        or 'setAttribute(\n        "action"' in text
        or 'setAttribute("action"' in text
    )
    assert 'getAttribute("action")' in text
    assert "els.disposeForm.action" not in text


def test_carousel_js_marks_only_current_frame() -> None:
    # happy — ISS-021: no batch-wide mark sync
    text = Path("src/interfaces/admin/static/visit_photo_review_queue.js").read_text(
        encoding="utf-8"
    )
    assert "syncMarkToBatchFrames" not in text
    assert 'body.set("index", String(frame.index))' in text
    assert "applyMarkToCurrentFrame" in text


def test_carousel_problem_buttons_share_text_alignment() -> None:
    # happy — ISS-022: one left-align rule for tech / model / dispose
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    marker = "/* visit-photo-carousel-problem-align */"
    assert marker in css
    block_start = css.index(marker)
    block = css[block_start : block_start + 450]
    assert "demo-carousel-side .admin-btn" in block
    assert "justify-content: flex-start" in block
    assert "text-align: left" in block
    js = Path("src/interfaces/admin/static/visit_photo_review_queue.js").read_text(encoding="utf-8")
    assert 'b.className = "admin-btn"' in js
    assert "admin-btn-secondary" in js
    assert "visit-photo-dispose-group" in js


def test_dispose_route_absent_on_other_group() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store, wire_dispose=True)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_CUP}/dispose",
        data={"index": "0", "action": "trash"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_dispose_forbidden_without_panel() -> None:
    # error
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        panels=frozenset({AdminPanel.ROSTER}),
        wire_dispose=True,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose",
        data={"index": "0", "action": "trash"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_dispose_forbidden_bad_origin() -> None:
    # error
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose",
        data={"index": "0", "action": "trash"},
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_dispose_maps_index_errors() -> None:
    # error
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,), neighbors=((_CUP, (1,)),))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        batch=_accepted_batch(indexes=(0, 1)),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    missing_file = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose",
        data={"index": "9", "action": "trash"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert missing_file.status_code == 422
    not_unrecognized = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose",
        data={"index": "1", "action": "content", "target_group_id": _GROUP},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert not_unrecognized.status_code == 409


def test_unrecognized_block_dispose_renders_group_buttons() -> None:
    # happy — content groups as buttons; no select / «В группу»
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.get(f"/admin/visit-photo-review/blocks/{_BATCH}/{_UNRECOGNIZED}?day=all")
    assert response.status_code == 200
    html = response.text
    assert "<select" not in html
    assert "В группу" not in html
    assert 'name="target_group_id" value="waste_tank"' in html or f'value="{_GROUP}"' in html
    assert "visit-photo-dispose-group" in html
    assert "visit-photo-dispose-poor" in html
    assert "visit-photo-dispose-trash" in html
    assert "Бак отходов" in html
    assert "Стакан" in html


def test_unrecognized_block_has_dispose_actions_without_defect_form() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    html = client.get(f"/admin/visit-photo-review/blocks/{_BATCH}/{_UNRECOGNIZED}?day=all").text
    assert f"/admin/visit-photo-review/blocks/{_BATCH}/unrecognized/dispose" in html
    assert "Мусор" in html
    assert "Некачественное фото" in html
    assert "visit-photo-dispose-group" in html
    assert 'name="defect-' not in html
    assert ">Закрыть<" not in html


def test_visit_photo_review_list_renders_group_tiles() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-photo-review?day=all")
    assert response.status_code == 200
    html = response.text
    assert "demo-group-grid" in html
    assert "demo-group-card" in html
    assert "Бак отходов" in html
    assert "<table>" not in html
    assert "admin-save-bar" not in html


def test_list_filter_all_vs_default_unviewed() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0, 1))
    store.save_frame_view(
        FrameView(
            batch_id=_BATCH,
            index=0,
            actor_user_id="1001",
            viewed_at=_FROZEN_NOW,
        )
    )
    store.save_frame_view(
        FrameView(
            batch_id=_BATCH,
            index=1,
            actor_user_id="1001",
            viewed_at=_FROZEN_NOW,
        )
    )
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    default_html = client.get("/admin/visit-photo-review?day=all").text
    assert "Бак отходов" not in default_html or 'data-group-id="waste_tank"' not in default_html
    assert 'value="unviewed"' in default_html
    all_html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert 'data-group-id="waste_tank"' in all_html
    assert "Бак отходов" in all_html


def test_list_empty_missing_group_not_tiled() -> None:
    # happy — ISS-023: zero frames → no review tile
    store = MemoryReviewStore()
    store.save_record(
        ReviewRecord(
            batch_id=_BATCH,
            group_id=_GROUP,
            record_kind="missing",
            indexes=(),
            defects=(),
            system_error=False,
            comment="",
            creator_kind="system",
            actor_user_id=None,
            saved_at=_FROZEN_NOW,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert 'data-group-id="waste_tank"' not in html
    assert "demo-group-card--missing" not in html
    assert "demo-carousel" in html


def test_carousel_open_records_frame_view() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/frames/{_BATCH}/0/view",
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {200, 204}
    view = store.find_frame_view(_BATCH, 0)
    assert view is not None
    assert view.actor_user_id == str(_ADMIN_TG)


def test_instant_mark_toggle_clears_when_empty() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    first = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
        data={"defect_code": "dirty", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert first.status_code == 200
    record = store.find_frame_record(_BATCH, _GROUP, 0)
    assert record is not None
    assert {mark.code for mark in record.defects} == {"dirty"}
    second = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
        data={"defect_code": "dirty", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert second.status_code == 200
    assert store.find_frame_record(_BATCH, _GROUP, 0) is None


def test_instant_mark_scopes_to_current_frame_only() -> None:
    # happy — sibling frame in same group stays unmarked
    store = MemoryReviewStore()
    _seed_assignment(store, indexes=(0, 1))
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
        data={"defect_code": "dirty", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert store.find_frame_record(_BATCH, _GROUP, 0) is not None
    assert store.find_frame_record(_BATCH, _GROUP, 1) is None


def test_instant_mark_without_frame_index_rejected() -> None:
    # error
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
        data={"defect_code": "dirty"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert store.find_frame_record(_BATCH, _GROUP, 0) is None


def test_unrecognized_carousel_has_dispose_not_defects() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_unrecognized(store, indexes=(0,))
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=_catalog_with_reserved(),
        wire_dispose=True,
    )
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert 'data-group-id="unrecognized"' in html
    assert "dispose" in html
    assert 'id="dispose-content-actions"' in html
    assert "visit-photo-dispose-poor" in html
    assert "visit-photo-dispose-trash" in html
    assert 'id="dispose-target"' not in html
    assert "admin-save-bar" not in html


def _assert_groups_workspace_tab_absent(html: str) -> None:
    assert 'data-tab="groups"' not in html
    tablist_idx = html.find('class="admin-workspace-tabs"')
    assert tablist_idx >= 0
    panel_idx = html.find('class="admin-workspace-panel"', tablist_idx)
    assert panel_idx > tablist_idx
    assert "Группы" not in html[tablist_idx:panel_idx]


def test_review_screen_has_no_history_link() -> None:
    # happy — ISS-020
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all").text
    assert "История" not in html
    assert "/visit-photo-review/history" not in html
    assert "Разбор" in html
    assert "Проблемы" in html
    _assert_groups_workspace_tab_absent(html)


def test_instant_mark_save_reject_surfaces_message() -> None:
    # error
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/blocks/{_BATCH}/{_GROUP}/mark",
        data={"defect_code": "dirty", "index": "0"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert response.status_code != 500
    body = response.text.lower()
    assert "error" in body or "назначен" in body or "reject" in body or "нет" in body


def test_visit_photo_review_has_workspace_tabs() -> None:
    # happy
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all").text
    assert "admin-workspace-tabs" in html
    assert "Разбор" in html
    assert "Проблемы" in html
    assert html.index("Разбор") < html.index("Проблемы")
    assert 'data-tab="review"' in html
    assert 'data-tab="problems"' in html
    _assert_groups_workspace_tab_absent(html)


def test_groups_tab_absent() -> None:
    # happy — ISS-425: catalog tab removed from workspace
    app, _deps, _store, _storage = _build_app(catalog=_catalog_with_reserved())
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=groups").text
    _assert_groups_workspace_tab_absent(html)
    assert "demo-groups-list" not in html


def test_groups_routes_forbidden_without_panel() -> None:
    # error
    app, _deps, _store, _storage = _build_app(
        panels=frozenset({AdminPanel.ROSTER}),
        catalog=_catalog_with_reserved(),
        wire_group_editor=True,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/visit-photo-review?day=all&tab=groups").status_code == 403
    assert client.get(f"/admin/visit-photo-review/groups/{_GROUP}").status_code == 403
    assert (
        client.post(
            f"/admin/visit-photo-review/groups/{_GROUP}",
            data={"defect_code_0": "x", "defect_label_0": "y"},
            headers={"origin": "http://testserver"},
        ).status_code
        == 403
    )


def test_group_editor_content_has_defects_and_save() -> None:
    # happy
    app, _deps, _store, _storage = _build_app(
        catalog=_catalog_with_reserved(),
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)
    html = client.get(f"/admin/visit-photo-review/groups/{_GROUP}").text
    assert "Бак отходов" in html
    assert "Проблемы" in html or "defect" in html.lower()
    assert "Подпись" in html
    assert ">Код<" not in html and ">Код\n" not in html
    assert 'type="hidden" name="defect_code_' in html or 'name="defect_code_' in html
    assert "admin-save-bar" in html
    assert "Сохранить" in html
    assert 'type="file"' in html
    assert 'enctype="multipart/form-data"' in html or "multipart/form-data" in html


def test_group_editor_js_adds_label_without_manual_code() -> None:
    # happy — ISS-019
    text = Path("src/interfaces/admin/static/visit_photo_review_groups.js").read_text(
        encoding="utf-8"
    )
    assert "defect_label_" in text
    assert "Код" not in text
    assert "defect_code_" not in text


def test_group_editor_photo_only_hides_defects() -> None:
    # edge
    app, _deps, _store, _storage = _build_app(
        catalog=_catalog_with_reserved(),
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)
    html = client.get(f"/admin/visit-photo-review/groups/{_TRASH}").text
    assert "Мусор" in html
    assert 'type="file"' in html
    assert "admin-save-bar" in html
    assert "Сохранить" in html
    assert "Проблемы фото" not in html
    assert 'name="defect_code' not in html
    assert "Добавить проблему" not in html


def test_saved_defects_appear_on_review_carousel_buttons() -> None:
    # happy
    catalog = _catalog_with_reserved()
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(
        store=store,
        catalog=catalog,
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)
    save = client.post(
        f"/admin/visit-photo-review/groups/{_GROUP}",
        data={
            "defect_code_0": "dirty",
            "defect_label_0": "Грязь",
            "defect_code_1": "overflow",
            "defect_label_1": "Переполнен",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert save.status_code in {303, 302}
    list_html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert "overflow" in list_html
    assert "Переполнен" in list_html


def test_group_editor_create_slugs_code_from_label() -> None:
    # happy — ISS-019 create without manual code
    catalog = _catalog_with_reserved()
    app, _deps, _store, _storage = _build_app(
        catalog=catalog,
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)
    save = client.post(
        f"/admin/visit-photo-review/groups/{_GROUP}",
        data={"defect_label_0": "Грязь на стенке"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert save.status_code in {303, 302}
    group = catalog.load().group(_GROUP)
    assert group is not None
    assert group.defects == (DefectButton(code="gryaz-na-stenke", label="Грязь на стенке"),)


def test_review_tab_still_renders_without_history() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_assignment(store)
    store.save_record(
        ReviewRecord(
            batch_id=_BATCH,
            group_id=_GROUP,
            record_kind="human",
            indexes=(0,),
            defects=(DefectMark(code="dirty", label="Грязь"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="1001",
            saved_at=_FROZEN_NOW,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )
    app, _deps, _store, _storage = _build_app(store=store, catalog=_catalog_with_reserved())
    client = TestClient(app)
    _login(client)
    review_html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert "demo-group-grid" in review_html
    assert "demo-group-card" in review_html
    assert "admin-workspace-tabs" in review_html
    assert client.get("/admin/visit-photo-review/history?day=all").status_code == 404


def test_group_editor_bad_image_rejects_without_touching_catalog() -> None:
    # error
    catalog = _catalog_with_reserved()
    before = catalog.load().group(_GROUP)
    assert before is not None
    before_codes = tuple(item.code for item in before.defects)
    app, _deps, _store, _storage = _build_app(
        catalog=catalog,
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/groups/{_GROUP}",
        data={
            "defect_code_0": "newcode",
            "defect_label_0": "Новая",
        },
        files={"photo": ("bad.txt", b"not-an-image", "text/plain")},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert response.status_code != 500
    after = catalog.load().group(_GROUP)
    assert after is not None
    assert tuple(item.code for item in after.defects) == before_codes


def test_group_editor_save_photo_only_avatar() -> None:
    # happy
    avatars = MemoryGroupAvatarWriter()
    app, _deps, _store, _storage = _build_app(
        catalog=_catalog_with_reserved(),
        wire_group_editor=True,
        avatar_store=avatars,
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        f"/admin/visit-photo-review/groups/{_TRASH}",
        files={"photo": ("trash.jpg", _JPEG_BYTES, "image/jpeg")},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}
    assert avatars.read_avatar(_TRASH) is not None
    assert avatars.read_avatar(_TRASH).content == _JPEG_BYTES  # type: ignore[union-attr]


def test_group_editor_multipart_exception_does_not_wipe_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error
    from starlette.formparsers import MultiPartException, MultiPartParser

    catalog = _catalog_with_reserved()
    before = catalog.load().group(_GROUP)
    assert before is not None
    before_codes = tuple(item.code for item in before.defects)
    app, _deps, _store, _storage = _build_app(
        catalog=catalog,
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)

    async def _boom(self: MultiPartParser) -> object:  # noqa: ARG001
        raise MultiPartException("bad multipart")

    monkeypatch.setattr(MultiPartParser, "parse", _boom)
    response = client.post(
        f"/admin/visit-photo-review/groups/{_GROUP}",
        files={"photo": ("x.jpg", _JPEG_BYTES, "image/jpeg")},
        data={"defect_code_0": "should_not_apply", "defect_label_0": "X"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    after = catalog.load().group(_GROUP)
    assert after is not None
    assert tuple(item.code for item in after.defects) == before_codes


def test_group_editor_post_catalog_unavailable_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error
    from src.application.visit_photo_review.ports import CatalogUnavailable
    from src.interfaces.admin.routes import visit_photo_review as routes_mod

    catalog = _catalog_with_reserved()
    app, _deps, _store, _storage = _build_app(
        catalog=catalog,
        wire_group_editor=True,
    )
    client = TestClient(app)
    _login(client)

    def _raise(*_a: object, **_k: object) -> object:
        raise CatalogUnavailable("down")

    monkeypatch.setattr(routes_mod, "_find_editor_group", _raise)
    response = client.post(
        f"/admin/visit-photo-review/groups/{_GROUP}",
        data={"defect_code_0": "dirty", "defect_label_0": "Грязь"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 503


def _seed_problem_record(store: MemoryReviewStore) -> None:
    store.save_record(
        ReviewRecord(
            batch_id=_BATCH,
            group_id=_GROUP,
            record_kind="human",
            indexes=(0, 1),
            defects=(DefectMark(code="dirty", label="Грязь"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="1001",
            saved_at=_FROZEN_NOW,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_FROZEN_NOW,
        )
    )


def test_visit_photo_review_has_problems_tab() -> None:
    # happy
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all").text
    assert "admin-workspace-tabs" in html
    assert "Разбор" in html
    assert "Проблемы" in html
    assert html.index("Разбор") < html.index("Проблемы")
    _assert_groups_workspace_tab_absent(html)
    assert 'data-tab="problems"' in html
    problems = client.get("/admin/visit-photo-review?day=all&tab=problems")
    assert problems.status_code == 200
    assert 'aria-selected="true"' in problems.text
    assert 'data-tab="problems"' in problems.text


def test_problems_tab_renders_table_columns() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_problem_record(store)
    app, _deps, _store, storage = _build_app(store=store)
    storage._objects["k-0"] = _JPEG_BYTES
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems").text
    assert "admin-problems" in html or "problems-table" in html or "admin-problems-table" in html
    for header in ("Фото", "Дата и время", "Локация", "Техник", "Группа", "Проблема"):
        assert header in html
    assert "Грязь" in html
    assert "Бак отходов" in html
    assert "admin-save-bar" not in html
    assert "demo-problems" not in html
    assert "demo-thumb" not in html
    assert "demo-lightbox" not in html


def test_problems_rows_embedded_when_default_tab_review() -> None:
    # happy — client-side tab switch must not show empty Problems panel
    store = MemoryReviewStore()
    _seed_problem_record(store)
    app, _deps, _store, storage = _build_app(store=store)
    storage._objects["k-0"] = _JPEG_BYTES
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all").text
    problems_panel = _problems_panel(html)
    assert "Грязь" in problems_panel
    assert "problems-table" in problems_panel or "problems-body" in problems_panel


def test_problems_tab_sticky_filters_chrome() -> None:
    # happy
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems").text
    assert "admin-roster-chrome" in html
    assert "admin-roster-chrome-pin" in html
    assert "admin-problems-chrome" in html or "admin-problems" in html
    assert 'placeholder="дд.мм.гг"' in html or "дд.мм.гг" in html
    assert "aria-label=" in html
    problems_start = html.find('class="admin-workspace-panel" data-tab="problems"')
    lightbox_start = html.find("admin-lightbox", problems_start)
    problems_panel = html[problems_start:lightbox_start]
    assert "<label>Локация" not in problems_panel
    assert "<label>Техник" not in problems_panel
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert "admin-problems-chrome" in css
    assert "--admin-bg" in css


def test_problems_tab_empty_state() -> None:
    # edge
    app, _deps, _store, _storage = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems").text
    assert "Нет помеченных проблем" in html or "нет проблем" in html.lower()


def test_problems_tab_forbidden_without_panel() -> None:
    # error
    app, _deps, _store, _storage = _build_app(panels=frozenset({AdminPanel.ROSTER}))
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/visit-photo-review?day=all&tab=problems").status_code == 403


def test_review_tab_unchanged_without_groups_workspace_tab() -> None:
    # edge — ISS-425
    store = MemoryReviewStore()
    _seed_assignment(store)
    app, _deps, _store, _storage = _build_app(store=store, catalog=_catalog_with_reserved())
    client = TestClient(app)
    _login(client)
    review_html = client.get("/admin/visit-photo-review?day=all&view=all").text
    assert "demo-group-grid" in review_html
    assert "demo-group-card" in review_html
    assert "demo-carousel" in review_html
    _assert_groups_workspace_tab_absent(review_html)


def test_problems_lightbox_no_panel_or_arrows() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_problem_record(store)
    app, _deps, _store, storage = _build_app(store=store)
    storage._objects["k-0"] = _JPEG_BYTES
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems").text
    lightbox_idx = html.find("admin-problems-lightbox")
    if lightbox_idx < 0:
        lightbox_idx = html.find("admin-lightbox")
    assert lightbox_idx >= 0
    lightbox_chunk = html[lightbox_idx : lightbox_idx + 1500]
    assert "demo-carousel-side" not in lightbox_chunk
    assert "carousel-side" not in lightbox_chunk
    assert 'aria-label="Предыдущее' not in lightbox_chunk
    assert 'aria-label="Следующее' not in lightbox_chunk
    assert "admin-lightbox-close" in lightbox_chunk or 'aria-label="Закрыть"' in lightbox_chunk
    js = Path("src/interfaces/admin/static/visit_photo_review_problems.js").read_text(
        encoding="utf-8"
    )
    assert "Escape" in js


def _problems_panel(html: str) -> str:
    start = html.find('class="admin-workspace-panel" data-tab="problems"')
    assert start >= 0
    next_panel = html.find('class="admin-workspace-panel" data-tab="', start + 1)
    end = next_panel if next_panel >= 0 else len(html)
    return html[start:end]


def _problem_select(panel: str) -> str:
    marker = 'aria-label="Проблема"'
    at = panel.find(marker)
    assert at >= 0
    start = panel.rfind("<select", 0, at)
    end = panel.find("</select>", at)
    assert start >= 0
    assert end > start
    return panel[start:end]


def test_problems_filters_are_column_selects() -> None:
    # happy
    store = MemoryReviewStore()
    _seed_problem_record(store)
    catalog = FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id=_GROUP,
                    title="Бак отходов",
                    required=True,
                    defects=(
                        DefectButton(code="dirty", label="Грязь"),
                        DefectButton(code="overflow", label="Переполнен"),
                    ),
                ),
                CatalogGroup(
                    group_id=_CUP,
                    title="Стакан",
                    required=False,
                    defects=(DefectButton(code="missing", label="Нет стакана"),),
                ),
            )
        )
    )
    app, _deps, _store, storage = _build_app(store=store, catalog=catalog)
    storage._objects["k-0"] = _JPEG_BYTES
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems&group_id=waste_tank").text
    panel = _problems_panel(html)
    assert panel.count("<select") == 4
    assert panel.count('type="text"') == 1
    for label in ("Локация", "Техник", "Группа фото", "Проблема"):
        assert f'aria-label="{label}"' in panel
    assert 'value="m-1"' in panel
    assert 'value="t-1"' in panel
    assert "Бак отходов" in panel
    assert "Стакан" in panel
    problem = _problem_select(panel)
    assert "disabled" not in problem
    assert "Грязь" in problem
    assert "Переполнен" in problem
    assert "Нет стакана" not in problem
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    header_at = css.find(".admin-header-table {")
    assert header_at >= 0
    assert "table-layout: auto" in css[header_at : header_at + 220]
    js = Path("src/interfaces/admin/static/visit_photo_review_problems.js").read_text(
        encoding="utf-8"
    )
    assert "syncProblemColumns" in js
    assert "problems-filter-groups" in js


def test_problem_filter_stays_closed_until_group_is_chosen() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_problem_record(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems&defect=nomatch").text
    panel = _problems_panel(html)
    problem = _problem_select(panel)
    assert "disabled" in problem
    assert "Сначала выберите группу фото" in problem
    assert "Грязь" in panel
    assert "nomatch" not in problem


def test_problem_filter_drops_defect_from_another_group() -> None:
    # error: чужая проблема не сужает таблицу и не попадает в список
    store = MemoryReviewStore()
    _seed_problem_record(store)
    catalog = FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id=_GROUP,
                    title="Бак отходов",
                    required=True,
                    defects=(DefectButton(code="dirty", label="Грязь"),),
                ),
                CatalogGroup(
                    group_id=_CUP,
                    title="Стакан",
                    required=False,
                    defects=(DefectButton(code="missing", label="Нет стакана"),),
                ),
            )
        )
    )
    app, _deps, _store, _storage = _build_app(store=store, catalog=catalog)
    client = TestClient(app)
    _login(client)
    html = client.get(
        "/admin/visit-photo-review?day=all&tab=problems&group_id=waste_tank&defect=missing"
    ).text
    panel = _problems_panel(html)
    assert "Грязь" in panel
    problem = _problem_select(panel)
    assert "Нет стакана" not in problem
    assert "selected" not in problem


def test_problems_lightbox_missing_photo_placeholder() -> None:
    # edge
    store = MemoryReviewStore()
    _seed_problem_record(store)
    app, _deps, _store, _storage = _build_app(store=store)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-review?day=all&tab=problems").text
    assert (
        "admin-thumb--placeholder" in html
        or "admin-problems-thumb--placeholder" in html
        or "placeholder" in html.lower()
    )
