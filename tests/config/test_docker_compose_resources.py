from __future__ import annotations

from pathlib import Path

import yaml
from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


class ComposeSafeLoader(SafeLoader):
    """SafeLoader with Compose merge tags (!override, etc.) for prod overlay tests."""


def _compose_tag_constructor(loader: ComposeSafeLoader, tag_suffix: str, node: Node) -> object:
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    raise yaml.constructor.ConstructorError(
        None,
        None,
        f"unsupported compose tag {tag_suffix!r}",
        node.start_mark,
    )


ComposeSafeLoader.add_multi_constructor("!", _compose_tag_constructor)


def _load_compose_yaml(text: str) -> object:
    return yaml.load(text, Loader=ComposeSafeLoader)


def test_prod_compose_sets_resource_limits_for_core_services() -> None:
    text = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    data = _load_compose_yaml(text)
    expected = {
        "app": {"cpus": "1.0", "memory": "1280M"},
        "effects-worker": {"cpus": "0.5", "memory": "768M"},
        "matrix-worker": {"cpus": "0.5", "memory": "512M"},
        "sales-monitoring-worker": {"cpus": "0.5", "memory": "384M"},
        "event-reminders-worker": {"cpus": "0.5", "memory": "256M"},
        "mongo": {"cpus": "0.75", "memory": "2048M"},
        "redis": {"cpus": "0.25", "memory": "128M"},
        "caddy": {"cpus": "0.25", "memory": "128M"},
    }
    for service, limits in expected.items():
        assert data["services"][service]["deploy"]["resources"]["limits"] == limits


def _volume_bind_targets(volumes: list[object]) -> list[str]:
    targets: list[str] = []
    for entry in volumes:
        if isinstance(entry, dict) and entry.get("type") == "bind":
            target = entry.get("target")
            if isinstance(target, str):
                targets.append(target)
    return targets


def test_effects_worker_mounts_google_forms_user_oauth_like_app() -> None:
    """effects-worker refreshes Telegram workspace links and needs the same OAuth bind as app."""
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    data = _load_compose_yaml(text)
    services = data["services"]
    oauth_target = "/app/google-forms-user-oauth.json"
    assert oauth_target in _volume_bind_targets(services["app"]["volumes"])
    assert oauth_target in _volume_bind_targets(services["effects-worker"]["volumes"])
    assert (
        services["effects-worker"]["environment"]["GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE"]
        == "google-forms-user-oauth.json"
    )
