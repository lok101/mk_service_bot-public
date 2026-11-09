from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from beartype import beartype

from src.domain.system_user import NAV_ALIAS_PANELS, PLANOGRAM_OPERATOR_NAV_PANELS, AdminPanel


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavPanelNode:
    kind: Literal["panel"]
    panel: AdminPanel


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavFolderNode:
    kind: Literal["folder"]
    folder_id: str
    title: str
    children: tuple[AdminPanel, ...]


AdminNavNode = AdminNavPanelNode | AdminNavFolderNode


@beartype
@dataclass(frozen=True, slots=True)
class AdminNavStructure:
    nodes: tuple[AdminNavNode, ...]


class AdminNavStructureInvalid(ValueError):
    """Invalid nav structure document."""


@beartype
@dataclass(frozen=True, slots=True)
class ResolvedNavPanel:
    kind: Literal["panel"]
    panel: AdminPanel


@beartype
@dataclass(frozen=True, slots=True)
class ResolvedNavFolder:
    kind: Literal["folder"]
    folder_id: str
    title: str
    children: tuple[AdminPanel, ...]


ResolvedNavNode = ResolvedNavPanel | ResolvedNavFolder


@runtime_checkable
class AdminNavStructureStore(Protocol):
    def get(self) -> AdminNavStructure | None: ...

    def save(self, structure: AdminNavStructure) -> None: ...


def _panel_from_raw(raw_panel: object) -> AdminPanel:
    if not isinstance(raw_panel, str):
        raise AdminNavStructureInvalid("panel id must be a string")
    try:
        return AdminPanel(raw_panel)
    except ValueError as exc:
        raise AdminNavStructureInvalid(f"unknown panel: {raw_panel!r}") from exc


def _parse_node(raw_node: object) -> AdminNavNode:
    if not isinstance(raw_node, dict):
        raise AdminNavStructureInvalid("node must be an object")
    node_type = raw_node.get("type")
    if node_type == "panel":
        return AdminNavPanelNode(kind="panel", panel=_panel_from_raw(raw_node.get("panel")))
    if node_type == "folder":
        folder_id = raw_node.get("id")
        title = raw_node.get("title")
        children_raw = raw_node.get("children")
        if not isinstance(folder_id, str):
            raise AdminNavStructureInvalid("folder id must be a string")
        if not isinstance(title, str):
            raise AdminNavStructureInvalid("folder title must be a string")
        if not isinstance(children_raw, list):
            raise AdminNavStructureInvalid("folder children must be a list")
        children: list[AdminPanel] = []
        for child in children_raw:
            if isinstance(child, dict):
                raise AdminNavStructureInvalid(
                    "folder children must be panel ids, not nested nodes"
                )
            children.append(_panel_from_raw(child))
        return AdminNavFolderNode(
            kind="folder",
            folder_id=folder_id,
            title=title,
            children=tuple(children),
        )
    raise AdminNavStructureInvalid(f"unknown node type: {node_type!r}")


@beartype
def validate_admin_nav_structure(nodes: tuple[AdminNavNode, ...]) -> AdminNavStructure:
    """unique AdminPanel across tree; folder title strip() non-empty; folder_id non-empty."""
    seen: set[AdminPanel] = set()
    for node in nodes:
        if node.kind == "panel":
            if node.panel in seen:
                raise AdminNavStructureInvalid(f"duplicate panel: {node.panel.value}")
            seen.add(node.panel)
            continue
        if not node.folder_id:
            raise AdminNavStructureInvalid("folder id must be non-empty")
        if not node.title.strip():
            raise AdminNavStructureInvalid("folder title must be non-empty")
        folder_seen: set[AdminPanel] = set()
        for child in node.children:
            if child in folder_seen:
                raise AdminNavStructureInvalid(f"duplicate panel in folder: {child.value}")
            folder_seen.add(child)
            if child in seen:
                raise AdminNavStructureInvalid(f"duplicate panel: {child.value}")
            seen.add(child)
    return AdminNavStructure(nodes=nodes)


@beartype
def parse_admin_nav_structure(raw: object) -> AdminNavStructure:
    """raw = list of dicts in spec Mongo `nodes` shape; then validate."""
    if not isinstance(raw, list):
        raise AdminNavStructureInvalid("nodes must be a list")
    nodes = tuple(_parse_node(item) for item in raw)
    return validate_admin_nav_structure(nodes)


@beartype
def default_admin_nav_structure() -> AdminNavStructure:
    """Seed: Roster; Visits; Settlement; Pricing; Справочники(Парк, Люди); nav_settings last."""
    return validate_admin_nav_structure(
        (
            AdminNavPanelNode(kind="panel", panel=AdminPanel.ROSTER),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.VISIT_BOARD),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.VISIT_PHOTO_REVIEW),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.SETTLEMENT_ANALYSIS),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.MATRIX_PRICING),
            AdminNavFolderNode(
                kind="folder",
                folder_id="directories",
                title="Справочники",
                children=(
                    AdminPanel.MASTER_DATA,
                    AdminPanel.USERS,
                    AdminPanel.TECHNICIANS,
                    AdminPanel.COMPANIES,
                    AdminPanel.DOMAIN_PRODUCTS,
                    AdminPanel.MICROMARKET_PLANOGRAMS,
                    AdminPanel.MATRIX_SKU_CATALOG,
                ),
            ),
            AdminNavPanelNode(kind="panel", panel=AdminPanel.NAV_SETTINGS),
        )
    )


@beartype
def admin_nav_structure_to_raw(structure: AdminNavStructure) -> list[dict[str, Any]]:
    """Serialize structure to Mongo `nodes` document shape."""
    raw: list[dict[str, Any]] = []
    for node in structure.nodes:
        if node.kind == "panel":
            raw.append({"type": "panel", "panel": node.panel.value})
            continue
        raw.append(
            {
                "type": "folder",
                "id": node.folder_id,
                "title": node.title,
                "children": [child.value for child in node.children],
            }
        )
    return raw


@beartype
def resolve_admin_nav_tree(
    structure: AdminNavStructure | None,
    *,
    allowed: frozenset[AdminPanel],
    mounted: frozenset[AdminPanel],
    all_panels: tuple[AdminPanel, ...] = tuple(AdminPanel),
) -> tuple[ResolvedNavNode, ...]:
    """Use default seed when structure is None. Filter by allowed∩mounted.
    Drop empty folders; keep one-child folders. Append missing panels at root end.
    Ignore panels in structure that are not in AdminPanel enum (already dropped at parse).
    """
    source = default_admin_nav_structure() if structure is None else structure
    all_set = frozenset(all_panels)

    def _visible(panel: AdminPanel) -> bool:
        if panel not in mounted or panel not in all_set:
            return False
        if panel in NAV_ALIAS_PANELS:
            return AdminPanel.MASTER_DATA in allowed
        if panel in PLANOGRAM_OPERATOR_NAV_PANELS:
            return AdminPanel.MICROMARKET_PLANOGRAMS in allowed
        return panel in allowed

    appeared: set[AdminPanel] = set()
    resolved: list[ResolvedNavNode] = []
    for node in source.nodes:
        if node.kind == "panel":
            if not _visible(node.panel):
                continue
            resolved.append(ResolvedNavPanel(kind="panel", panel=node.panel))
            appeared.add(node.panel)
            continue
        children = tuple(child for child in node.children if _visible(child))
        if not children:
            continue
        resolved.append(
            ResolvedNavFolder(
                kind="folder",
                folder_id=node.folder_id,
                title=node.title,
                children=children,
            )
        )
        appeared.update(children)
    for panel in all_panels:
        if panel in appeared or not _visible(panel):
            continue
        resolved.append(ResolvedNavPanel(kind="panel", panel=panel))
        appeared.add(panel)
    return tuple(resolved)


@beartype
def merge_mounted_panels_for_editor(
    structure: AdminNavStructure,
    *,
    mounted: frozenset[AdminPanel],
    all_panels: tuple[AdminPanel, ...] = tuple(AdminPanel),
) -> AdminNavStructure:
    """Append mounted panels missing from structure (nav-settings editor)."""
    appeared: set[AdminPanel] = set()
    for node in structure.nodes:
        if node.kind == "panel":
            appeared.add(node.panel)
        else:
            appeared.update(node.children)
    extra: list[AdminNavNode] = []
    for panel in all_panels:
        if panel in appeared or panel not in mounted:
            continue
        extra.append(AdminNavPanelNode(kind="panel", panel=panel))
    if not extra:
        return structure
    return validate_admin_nav_structure(structure.nodes + tuple(extra))
