from __future__ import annotations

from src.application.shared.admin_nav import (
    AdminNavFolderNode,
    AdminNavPanelNode,
    AdminNavStructure,
    AdminNavStructureInvalid,
    default_admin_nav_structure,
    merge_mounted_panels_for_editor,
    parse_admin_nav_structure,
    resolve_admin_nav_tree,
    validate_admin_nav_structure,
)
from src.application.shared.admin_nav_memory import InMemoryAdminNavStructureStore
from src.domain.system_user import AdminPanel


def test_validate_accepts_flat_and_one_level_folder() -> None:
    structure = validate_admin_nav_structure(
        (
            AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
            AdminNavFolderNode(
                kind="folder",
                folder_id="directories",
                title="Справочники",
                children=(AdminPanel.MASTER_DATA, AdminPanel.USERS),
            ),
        )
    )
    assert len(structure.nodes) == 2


def test_validate_rejects_duplicate_panel() -> None:
    try:
        validate_admin_nav_structure(
            (
                AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
                AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
            )
        )
    except AdminNavStructureInvalid:
        return
    raise AssertionError("expected AdminNavStructureInvalid")


def test_validate_rejects_empty_folder_title() -> None:
    try:
        validate_admin_nav_structure(
            (
                AdminNavFolderNode(
                    kind="folder",
                    folder_id="x",
                    title="   ",
                    children=(AdminPanel.ROSTER,),
                ),
            )
        )
    except AdminNavStructureInvalid:
        return
    raise AssertionError("expected AdminNavStructureInvalid")


def test_validate_rejects_nested_folder() -> None:
    try:
        parse_admin_nav_structure(
            [
                {
                    "type": "folder",
                    "id": "outer",
                    "title": "Outer",
                    "children": [
                        {"type": "folder", "id": "inner", "title": "Inner", "children": []}
                    ],
                }
            ]
        )
    except AdminNavStructureInvalid:
        return
    raise AssertionError("expected AdminNavStructureInvalid")


def test_validate_rejects_unknown_panel() -> None:
    try:
        parse_admin_nav_structure([{"type": "panel", "panel": "not_a_panel"}])
    except AdminNavStructureInvalid:
        return
    raise AssertionError("expected AdminNavStructureInvalid")


def test_default_seed_has_directories_folder() -> None:
    structure = default_admin_nav_structure()
    panels_flat: list[AdminPanel] = []
    folder_titles: list[str] = []
    folder_children: tuple[AdminPanel, ...] | None = None
    for node in structure.nodes:
        if node.kind == "panel":
            panels_flat.append(node.panel)
        else:
            folder_titles.append(node.title)
            folder_children = node.children
    assert "Справочники" in folder_titles
    assert folder_children == (
        AdminPanel.MASTER_DATA,
        AdminPanel.USERS,
        AdminPanel.TECHNICIANS,
        AdminPanel.COMPANIES,
        AdminPanel.DOMAIN_PRODUCTS,
        AdminPanel.MICROMARKET_PLANOGRAMS,
        AdminPanel.MATRIX_SKU_CATALOG,
    )
    assert AdminPanel.ROSTER in panels_flat
    assert AdminPanel.VISIT_BOARD in panels_flat
    assert AdminPanel.VISIT_PHOTO_REVIEW in panels_flat
    assert AdminPanel.SETTLEMENT_ANALYSIS in panels_flat
    assert AdminPanel.MATRIX_PRICING in panels_flat
    assert AdminPanel.NAV_SETTINGS in panels_flat
    visit_board_idx = panels_flat.index(AdminPanel.VISIT_BOARD)
    assert panels_flat[visit_board_idx + 1] is AdminPanel.VISIT_PHOTO_REVIEW
    last = structure.nodes[-1]
    assert last.kind == "panel"
    assert last.panel is AdminPanel.NAV_SETTINGS


def test_resolve_filters_permission_and_mount() -> None:
    structure = AdminNavStructure(
        nodes=(
            AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.USERS),
        )
    )
    tree = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.ROSTER}),
        mounted=frozenset({AdminPanel.ROSTER, AdminPanel.USERS}),
        all_panels=(AdminPanel.ROSTER, AdminPanel.USERS),
    )
    assert [n.panel for n in tree if n.kind == "panel"] == [AdminPanel.ROSTER]


def test_resolve_hides_empty_folder() -> None:
    structure = AdminNavStructure(
        nodes=(
            AdminNavFolderNode(
                kind="folder",
                folder_id="directories",
                title="Справочники",
                children=(AdminPanel.USERS,),
            ),
        )
    )
    tree = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.ROSTER}),
        mounted=frozenset({AdminPanel.ROSTER, AdminPanel.USERS}),
        all_panels=(AdminPanel.ROSTER, AdminPanel.USERS),
    )
    assert not any(n.kind == "folder" for n in tree)


def test_resolve_keeps_folder_with_one_child() -> None:
    structure = AdminNavStructure(
        nodes=(
            AdminNavFolderNode(
                kind="folder",
                folder_id="directories",
                title="Справочники",
                children=(AdminPanel.MASTER_DATA, AdminPanel.USERS),
            ),
        )
    )
    tree = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.MASTER_DATA}),
        mounted=frozenset({AdminPanel.MASTER_DATA, AdminPanel.USERS}),
        all_panels=(AdminPanel.MASTER_DATA, AdminPanel.USERS),
    )
    folders = [n for n in tree if n.kind == "folder"]
    assert len(folders) == 1
    assert folders[0].children == (AdminPanel.MASTER_DATA,)


def test_resolve_auto_appends_missing_panel() -> None:
    structure = AdminNavStructure(nodes=(AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),))
    tree = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS}),
        mounted=frozenset({AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS}),
        all_panels=(AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS),
    )
    panels = [n.panel for n in tree if n.kind == "panel"]
    assert panels[-1] is AdminPanel.NAV_SETTINGS


def test_resolve_drops_orphan_panel() -> None:
    structure = AdminNavStructure(
        nodes=(
            AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.NAV_SETTINGS),
        )
    )
    tree = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS}),
        mounted=frozenset({AdminPanel.ROSTER, AdminPanel.NAV_SETTINGS}),
        all_panels=(AdminPanel.ROSTER,),
    )
    panels = [n.panel for n in tree if n.kind == "panel"]
    assert AdminPanel.NAV_SETTINGS not in panels
    assert panels == [AdminPanel.ROSTER]


def test_resolve_uses_seed_when_structure_none() -> None:
    tree = resolve_admin_nav_tree(
        None,
        allowed=frozenset(AdminPanel),
        mounted=frozenset(AdminPanel),
        all_panels=tuple(AdminPanel),
    )
    titles = [n.title for n in tree if n.kind == "folder"]
    assert "Справочники" in titles
    last_panels = [n.panel for n in tree if n.kind == "panel"]
    assert AdminPanel.NAV_SETTINGS in last_panels


def test_memory_nav_store_missing_is_none() -> None:
    store = InMemoryAdminNavStructureStore()
    assert store.get() is None


def test_memory_nav_store_round_trip() -> None:
    store = InMemoryAdminNavStructureStore()
    structure = default_admin_nav_structure()
    store.save(structure)
    assert store.get() == structure


def test_resolve_sku_catalog_visible_with_own_panel_not_master_data() -> None:
    structure = AdminNavStructure(
        nodes=(AdminNavPanelNode(kind="panel", panel=AdminPanel.MATRIX_SKU_CATALOG),)
    )
    with_own = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.MATRIX_SKU_CATALOG}),
        mounted=frozenset({AdminPanel.MATRIX_SKU_CATALOG}),
        all_panels=(AdminPanel.MATRIX_SKU_CATALOG,),
    )
    assert [n.panel for n in with_own if n.kind == "panel"] == [AdminPanel.MATRIX_SKU_CATALOG]
    master_only = resolve_admin_nav_tree(
        structure,
        allowed=frozenset({AdminPanel.MASTER_DATA}),
        mounted=frozenset({AdminPanel.MATRIX_SKU_CATALOG}),
        all_panels=(AdminPanel.MATRIX_SKU_CATALOG,),
    )
    assert [n.panel for n in master_only if n.kind == "panel"] == []


def test_merge_mounted_panels_for_editor_appends_missing() -> None:
    structure = AdminNavStructure(nodes=(AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),))
    merged = merge_mounted_panels_for_editor(
        structure,
        mounted=frozenset({AdminPanel.ROSTER, AdminPanel.TECHNICIANS}),
    )
    panels = [n.panel for n in merged.nodes if n.kind == "panel"]
    assert panels == [AdminPanel.ROSTER, AdminPanel.TECHNICIANS]


def _directory_children(tree: tuple[object, ...]) -> tuple[AdminPanel, ...]:
    folder = next(node for node in tree if getattr(node, "kind", None) == "folder")
    return folder.children


def test_nav_planogram_only_does_not_see_products() -> None:
    # edge — LOK-240: MICROMARKET alone must not surface Товары
    mounted = frozenset(
        {
            AdminPanel.MASTER_DATA,
            AdminPanel.DOMAIN_PRODUCTS,
            AdminPanel.MICROMARKET_PLANOGRAMS,
            AdminPanel.MATRIX_SKU_CATALOG,
        }
    )
    operator = resolve_admin_nav_tree(
        default_admin_nav_structure(),
        allowed=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}),
        mounted=mounted,
    )
    operator_children = _directory_children(operator)
    assert AdminPanel.MICROMARKET_PLANOGRAMS in operator_children
    assert AdminPanel.DOMAIN_PRODUCTS not in operator_children
    assert AdminPanel.MASTER_DATA not in operator_children
    assert AdminPanel.MATRIX_SKU_CATALOG not in operator_children

    products = resolve_admin_nav_tree(
        default_admin_nav_structure(),
        allowed=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
        mounted=mounted,
    )
    products_children = _directory_children(products)
    assert AdminPanel.DOMAIN_PRODUCTS in products_children
    assert AdminPanel.MICROMARKET_PLANOGRAMS not in products_children

    keeper = resolve_admin_nav_tree(
        default_admin_nav_structure(),
        allowed=frozenset({AdminPanel.MASTER_DATA}),
        mounted=mounted,
    )
    keeper_children = _directory_children(keeper)
    assert AdminPanel.MASTER_DATA in keeper_children
    assert AdminPanel.MATRIX_SKU_CATALOG not in keeper_children
    assert AdminPanel.MICROMARKET_PLANOGRAMS not in keeper_children
    assert AdminPanel.DOMAIN_PRODUCTS not in keeper_children


def test_resolve_hides_fridge_item_when_only_products_are_mounted() -> None:
    tree = resolve_admin_nav_tree(
        default_admin_nav_structure(),
        allowed=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS, AdminPanel.DOMAIN_PRODUCTS}),
        mounted=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.MICROMARKET_PLANOGRAMS}),
    )
    # Панель в mounted здесь только если тест сам её передал. Без неё пункт холодильников
    # не появляется: экран холодильника не смонтирован.
    hidden = resolve_admin_nav_tree(
        default_admin_nav_structure(),
        allowed=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
        mounted=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
    )
    assert AdminPanel.DOMAIN_PRODUCTS in _directory_children(hidden)
    assert AdminPanel.MICROMARKET_PLANOGRAMS not in _directory_children(hidden)
    assert AdminPanel.MICROMARKET_PLANOGRAMS in _directory_children(tree)
    assert AdminPanel.DOMAIN_PRODUCTS in _directory_children(tree)
