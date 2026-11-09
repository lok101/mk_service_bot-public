from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.admin.roster_view import build_roster_view_model

_VIEW_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _matching_stores(
    *,
    machine_id: str = "101",
    technician_id: str = "001",
    weekdays: frozenset[int] = frozenset(),
) -> tuple[InMemoryLocationRosterDraftStore, InMemoryLocationRosterStore]:
    entry = LocationRosterEntry(
        machine_id=MachineId(machine_id),
        technician_id=TechnicianId(technician_id),
        service_weekdays=weekdays,
        updated_at=_VIEW_NOW,
        updated_by_telegram_user_id=1,
    )
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all((entry,))
    draft.replace_all((entry,))
    return draft, applied


_DIR_HEADER = [
    "",
    "Создание",
    "Снятие",
    "ТТ",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]


def _dir_row(
    location_id: str,
    created: str,
    removed: str,
    machine: str,
    full_name: str,
    *,
    lat: str = "",
    lng: str = "",
) -> list[str]:
    return [
        location_id,
        created,
        removed,
        machine,
        "",
        full_name,
        "",
        "",
        "",
        lat,
        lng,
    ]


def _provider_with_catalog_and_tech() -> ReferenceDataProvider:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    # Required after inactive-filter: system_users() is read in build_roster_view_model.
    # Empty snapshot → options still include current assigned (001 from catalog row).
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(users_by_telegram_id={}, users_by_technician_id={}),
    )
    return provider


def test_build_roster_view_model_lists_unassigned_before_assigned() -> None:
    # happy: строки без техника выше строк с техником; вторичный порядок каталога
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["002", "Пётр"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "А", "Иван", "001"],
            ["102", "Б", "", ""],
            ["103", "В", "Пётр", "002"],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(users_by_telegram_id={}, users_by_technician_id={}),
    )
    now = _VIEW_NOW
    entries = (
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
        LocationRosterEntry(
            machine_id=MachineId("102"),
            technician_id=None,
            service_weekdays=frozenset({2}),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
        LocationRosterEntry(
            machine_id=MachineId("103"),
            technician_id=TechnicianId("002"),
            service_weekdays=frozenset({3}),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
    )
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all(entries)
    draft.replace_all(entries)
    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)
    assert [row.machine_id for row in view.rows] == ["102", "101", "103"]


def test_build_roster_view_model_all_assigned_keeps_catalog_order() -> None:
    # edge: все с техником — порядок каталога без перестановки по assignment
    provider = _provider_with_catalog_and_tech()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "А", "Иван", "001"],
            ["102", "Б", "Иван", "001"],
        ],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    now = _VIEW_NOW
    entries = (
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset(),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
        LocationRosterEntry(
            machine_id=MachineId("102"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset(),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
    )
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all(entries)
    draft.replace_all(entries)
    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)
    assert [row.machine_id for row in view.rows] == ["101", "102"]


def test_build_roster_view_model_all_unassigned_keeps_catalog_order() -> None:
    # edge: все без техника — вторичный порядок каталога
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "А", "", ""],
            ["102", "Б", "", ""],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(users_by_telegram_id={}, users_by_technician_id={}),
    )
    now = _VIEW_NOW
    entries = (
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=None,
            service_weekdays=frozenset(),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
        LocationRosterEntry(
            machine_id=MachineId("102"),
            technician_id=None,
            service_weekdays=frozenset(),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
    )
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all(entries)
    draft.replace_all(entries)
    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)
    assert [row.machine_id for row in view.rows] == ["101", "102"]


def test_build_roster_view_model_includes_machine_id_and_weekdays() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.machine_id == "101"
    assert row.location_name == "Школа"
    assert row.technician_id == "001"
    assert isinstance(row.weekdays, frozenset)
    assert row.updated_at == _VIEW_NOW.isoformat()
    assert view.draft_dirty is False
    assert len(view.technicians) == 1
    assert view.technicians[0].id == "001"
    assert view.technicians[0].name == "Иван"
    assert row.latitude is None
    assert row.longitude is None
    assert view.map_coordinates_available is False


def test_build_roster_view_model_uses_draft_assignment() -> None:
    provider = _provider_with_catalog_and_tech()
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("001"),
                service_weekdays=frozenset({1}),
                updated_at=now,
                updated_by_telegram_user_id=1,
            ),
        ),
    )
    draft.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("002"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=1,
        ),
        expected_updated_at=None,
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["002", "Пётр"]],
    )
    view = build_roster_view_model(
        provider,
        draft_store=draft,
        applied_store=applied,
    )
    assert view.rows[0].technician_id == "002"
    assert view.draft_dirty is True


def test_build_roster_view_model_sets_draft_dirty() -> None:
    provider = _provider_with_catalog_and_tech()
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    entry = LocationRosterEntry(
        machine_id=MachineId("101"),
        technician_id=TechnicianId("001"),
        service_weekdays=frozenset({1}),
        updated_at=now,
        updated_by_telegram_user_id=1,
    )
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    applied.replace_all((entry,))
    draft.replace_all((entry,))
    view = build_roster_view_model(
        provider,
        draft_store=draft,
        applied_store=applied,
    )
    assert view.draft_dirty is False


def test_build_roster_view_model_includes_coords_from_directory() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Школа full",
                lat="55,8",
                lng="49,1",
            ),
        ],
    )

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    assert view.map_coordinates_available is True
    row = view.rows[0]
    assert row.latitude == "55.8"
    assert row.longitude == "49.1"


def test_build_roster_view_model_uses_last_placement_coords() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-old",
                "01.01.2026",
                "01.05.2026",
                "101",
                "Старая",
                lat="10,0",
                lng="20,0",
            ),
            _dir_row(
                "loc-new",
                "02.05.2026",
                "",
                "101",
                "Новая",
                lat="55,8",
                lng="49,1",
            ),
        ],
    )

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    row = view.rows[0]
    assert row.latitude == "55.8"
    assert row.longitude == "49.1"


def test_build_roster_view_model_prefers_open_placement_over_later_closed_row() -> None:
    """Regression: master hydrate sorts by UUID; closed history can appear after open."""
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-new",
                "05.08.2026",
                "",
                "101",
                "Хлебозавод",
                lat="56,941196",
                lng="60,792692",
            ),
            _dir_row(
                "loc-old",
                "23.12.2024",
                "13.05.2026",
                "101",
                "Магнит",
                lat="56,867759",
                lng="60,537781",
            ),
        ],
    )

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    row = view.rows[0]
    assert row.latitude == "56.941196"
    assert row.longitude == "60.792692"


def test_build_roster_view_model_uses_latest_installed_when_all_placements_closed() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-newer",
                "02.05.2026",
                "01.06.2026",
                "101",
                "Новее",
                lat="55,8",
                lng="49,1",
            ),
            _dir_row(
                "loc-older",
                "01.01.2026",
                "01.05.2026",
                "101",
                "Старее",
                lat="10,0",
                lng="20,0",
            ),
        ],
    )

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    row = view.rows[0]
    assert row.latitude == "55.8"
    assert row.longitude == "49.1"


def test_build_roster_view_model_without_directory_has_no_coords() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    assert view.map_coordinates_available is False
    assert view.rows[0].latitude is None
    assert view.rows[0].longitude is None


def test_build_roster_view_model_skips_incomplete_coords() -> None:
    provider = _provider_with_catalog_and_tech()
    draft, applied = _matching_stores()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Без lng",
                lat="55,8",
                lng="",
            ),
        ],
    )

    view = build_roster_view_model(provider, draft_store=draft, applied_store=applied)

    assert view.map_coordinates_available is True
    assert view.rows[0].latitude is None
    assert view.rows[0].longitude is None


def test_roster_view_excludes_inactive_keeps_current_assigned() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Активный"], ["002", "Уволенный"], ["003", "Чужой inactive"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Точка", "Уволенный", "002"],
        ],
    )
    roster = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster)
    entry = LocationRosterEntry(
        machine_id=MachineId("101"),
        technician_id=TechnicianId("002"),
        service_weekdays=frozenset({0}),
        updated_at=datetime(2026, 8, 21, tzinfo=UTC),
        updated_by_telegram_user_id=1,
    )
    roster.save_batch(
        (entry,),
        actor_telegram_user_id=1,
        at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    draft = InMemoryLocationRosterDraftStore()
    draft.replace_all((entry,))
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                10: SystemUser(
                    user_id=SystemUserId("10"),
                    name="A",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=10,
                    technician_id=TechnicianId("001"),
                    company_roles=frozenset(),
                ),
                11: SystemUser(
                    user_id=SystemUserId("11"),
                    name="B",
                    role=BotRole.TECHNICIAN,
                    is_active=False,
                    telegram_user_id=11,
                    technician_id=TechnicianId("002"),
                    company_roles=frozenset(),
                ),
                12: SystemUser(
                    user_id=SystemUserId("12"),
                    name="C",
                    role=BotRole.TECHNICIAN,
                    is_active=False,
                    telegram_user_id=12,
                    technician_id=TechnicianId("003"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )
    view = build_roster_view_model(provider, draft_store=draft, applied_store=roster)
    option_ids = {t.id for t in view.technicians}
    assert "001" in option_ids
    assert "002" in option_ids
    assert "003" not in option_ids


def test_roster_excludes_inactive_technician() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Активный"], ["002", "Неактивный"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Точка", "Активный", "001"],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    draft, applied = _matching_stores()
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                10: SystemUser(
                    user_id=SystemUserId("10"),
                    name="A",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=10,
                    technician_id=TechnicianId("001"),
                    company_roles=frozenset(),
                ),
                11: SystemUser(
                    user_id=SystemUserId("11"),
                    name="B",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=11,
                    technician_id=TechnicianId("002"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )

    view = build_roster_view_model(
        provider,
        draft_store=draft,
        applied_store=applied,
        active_technician_ids=frozenset({TechnicianId("001")}),
    )

    option_ids = {t.id for t in view.technicians}
    assert "001" in option_ids
    assert "002" not in option_ids


def test_roster_keeps_assigned_inactive_visible() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Активный"], ["002", "Неактивный"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Точка", "Неактивный", "002"],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    draft, applied = _matching_stores(technician_id="002")
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                10: SystemUser(
                    user_id=SystemUserId("10"),
                    name="A",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=10,
                    technician_id=TechnicianId("001"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )

    view = build_roster_view_model(
        provider,
        draft_store=draft,
        applied_store=applied,
        active_technician_ids=frozenset({TechnicianId("001")}),
    )

    option_ids = {t.id for t in view.technicians}
    assert "001" in option_ids
    assert "002" in option_ids


def test_roster_still_requires_active_system_user() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Без пользователя"], ["002", "С пользователем"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Точка", "С пользователем", "002"],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    draft, applied = _matching_stores(technician_id="002")
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                20: SystemUser(
                    user_id=SystemUserId("20"),
                    name="Linked",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=20,
                    technician_id=TechnicianId("002"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )

    view = build_roster_view_model(
        provider,
        draft_store=draft,
        applied_store=applied,
        active_technician_ids=frozenset({TechnicianId("001"), TechnicianId("002")}),
    )

    option_ids = {t.id for t in view.technicians}
    assert "001" not in option_ids
    assert "002" in option_ids
