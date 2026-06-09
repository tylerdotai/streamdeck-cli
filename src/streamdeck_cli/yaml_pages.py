"""YAML page spec — human-editable page definitions.

A YAML file describes a page's actions. Use ``apply_yaml_spec`` to materialize
one into a profile (creating a new page), or ``render_yaml_spec`` to dump an
existing page back to YAML for diffing and editing.

Example spec::

    name: Coding
    controllers:
      keypad:
        actions:
          "0,0":
            title: VS Code
            icon: icons/vscode.png
            plugin: com.elgato.streamdeck.system.hotkey
      encoder:
        actions:
          "0":
            title: Volume
            icon: icons/volume.png

Icon paths are resolved against the ``icon_search_dirs`` you pass to
``apply_yaml_spec`` (typically a ``pages/<page-name>/icons/`` directory).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from streamdeck_cli.icons import set_icon
from streamdeck_cli.manifest import Page
from streamdeck_cli.writes import create_page

# ── Errors ──────────────────────────────────────────────────────────────────


class YamlSpecError(ValueError):
    """Raised when a YAML page spec is invalid."""


# ── Dataclass ───────────────────────────────────────────────────────────────


@dataclass
class YamlPageSpec:
    """Parsed YAML page spec.

    ``controllers`` is ``{controller_type: {actions: {key: action_dict}}}``,
    where ``controller_type`` is ``"keypad"`` or ``"encoder"`` (lowercase —
    maps to Stream Deck's ``"Keypad"`` / ``"Encoder"`` types).
    """

    name: str
    controllers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, text: str) -> YamlPageSpec:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise YamlSpecError(f"invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise YamlSpecError("spec must be a YAML mapping at the top level")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise YamlSpecError("spec must have a non-empty 'name' field")
        controllers = data.get("controllers") or {}
        if not isinstance(controllers, dict):
            raise YamlSpecError("'controllers' must be a mapping")
        # Normalize: ensure each controller is {actions: {...}}
        normalized: dict[str, dict[str, Any]] = {}
        for ctype, cdata in controllers.items():
            if not isinstance(cdata, dict):
                raise YamlSpecError(f"controller {ctype!r} must be a mapping")
            normalized[ctype] = {
                "actions": cdata.get("actions") or {},
            }
        return cls(name=name, controllers=normalized)


# ── Apply: YAML spec → page on disk ─────────────────────────────────────────


_CONTROLLER_TYPE_MAP = {
    "keypad": "Keypad",
    "encoder": "Encoder",
}


def _resolve_icon(icon_name: str, search_dirs: list[Path]) -> Path | None:
    """Find a PNG in any of the search dirs. Returns the first match."""
    for d in search_dirs:
        candidate = d / icon_name
        if candidate.is_file():
            return candidate
    return None


# ── Plugin registry ────────────────────────────────────────────────────────
# Maps the YAML `plugin:` value to the right action template.
# Each entry knows the plugin's display name and the Settings schema it expects.

_PLUGIN_REGISTRY: dict[str, dict[str, Any]] = {
    "com.elgato.streamdeck.system.hotkey": {
        "plugin_name": "Activate a Key Command",
        "default_settings": {},  # caller must provide Hotkeys list
    },
    "com.elgato.streamdeck.system.open": {
        "plugin_name": "Open",
        "default_settings": {"path": ""},
    },
    "com.elgato.streamdeck.system.website": {
        "plugin_name": "Website",
        "default_settings": {"openInBrowser": True, "path": ""},
    },
}


def _ensure_action_dict(spec: dict[str, Any]) -> dict[str, Any]:
    """Build a manifest action dict from a YAML action spec.

    Recognized spec keys (all optional except ``plugin`` and ``title``):
      - ``title``: display title
      - ``icon``:  filename resolved against ``--icons-dir`` (optional)
      - ``plugin``: plugin UUID; default is the system hotkey
      - ``settings``: free-form dict merged into the plugin's Settings
    """
    plugin_uuid = spec.get("plugin", "com.elgato.streamdeck.system.hotkey")
    plugin_info = _PLUGIN_REGISTRY.get(
        plugin_uuid,
        {
            "plugin_name": spec.get("plugin_name", plugin_uuid),
            "default_settings": {},
        },
    )

    settings: dict[str, Any] = {**plugin_info["default_settings"], **spec.get("settings", {})}

    action: dict[str, Any] = {
        "ActionID": "00000000-0000-0000-0000-000000000000",
        "Name": spec.get("title", ""),
        "UUID": plugin_uuid,
        "Plugin": {
            "Name": plugin_info["plugin_name"],
            "UUID": plugin_uuid,
            "Version": "1.0",
        },
        "LinkedTitle": True,
        "State": 0,
        "States": [{"Title": spec.get("title", "")}],
        "Settings": settings,
    }
    return action


def apply_yaml_spec(
    profile_dir: Path,
    spec: YamlPageSpec,
    *,
    icon_search_dirs: list[Path] | None = None,
) -> str:
    """Create a new page in ``profile_dir`` from ``spec``. Returns the new page UUID.

    ``icon_search_dirs`` is a list of directories to look up icon files
    referenced in the spec. The first match wins.
    """
    search_dirs = icon_search_dirs or []

    # First, create an empty page so we get a UUID + dir + manifest skeleton
    new_uuid = create_page(profile_dir, name=spec.name)
    page_dir = profile_dir / "Profiles" / new_uuid
    manifest_path = page_dir / "manifest.json"
    page_data = json.loads(manifest_path.read_text())

    # Now build controllers
    for ctype, cdata in spec.controllers.items():
        if ctype not in _CONTROLLER_TYPE_MAP:
            raise YamlSpecError(
                f"unknown controller type {ctype!r}; "
                f"expected one of {list(_CONTROLLER_TYPE_MAP)}"
            )
        sd_type = _CONTROLLER_TYPE_MAP[ctype]
        controller = next((c for c in page_data["Controllers"] if c["Type"] == sd_type), None)
        if controller is None:
            # Some fixture pages may not have both controllers; add it
            controller = {"Type": sd_type, "Actions": {}}
            page_data["Controllers"].append(controller)
        if controller.get("Actions") is None:
            controller["Actions"] = {}

        for key, action_spec in cdata["actions"].items():
            # Key format differs: keypad uses "col,row", encoder uses "0,row"
            sd_key = key if ctype == "keypad" else f"0,{key}" if "," not in key else key
            action = _ensure_action_dict(action_spec)

            # Resolve + assign icon
            icon_name = action_spec.get("icon")
            if icon_name:
                icon_path = _resolve_icon(icon_name, search_dirs)
                if icon_path is not None:
                    # set_icon writes the manifest with a default action + Icon field.
                    # We then read it back, copy the Icon/Encoder.Icon into our
                    # populated action, and persist.
                    set_icon(page_dir, sd_key, icon_path)
                    # Reload to get the post-set_icon manifest
                    page_data = json.loads(manifest_path.read_text())
                    ctrl = next(c for c in page_data["Controllers"] if c["Type"] == sd_type)
                    existing = (ctrl.get("Actions") or {}).get(sd_key, {})
                    existing_icon = existing.get("Icon")
                    existing_enc_icon = existing.get("Encoder", {}).get("Icon")
                    if existing_icon and ctype == "keypad":
                        action["Icon"] = existing_icon
                    elif existing_enc_icon and ctype == "encoder":
                        action["Encoder"] = {"Icon": existing_enc_icon}
                # If not found, silently skip (no Icon field set)

            if controller.get("Actions") is None:
                controller["Actions"] = {}
            controller["Actions"][sd_key] = action

    # Persist
    manifest_path.write_text(json.dumps(page_data, indent=4))
    return new_uuid


# ── Render: page → YAML ─────────────────────────────────────────────────────


def render_yaml_spec(page: Page) -> str:
    """Render a Page object back to YAML.

    The result is a string suitable for human editing. Icons are referenced
    by their on-page Images/ path (the caller is responsible for putting
    them back if they want to re-apply).
    """
    lines: list[str] = []
    lines.append(f"name: {page.name or '(unnamed)'}")
    lines.append("controllers:")

    for controller in page.controllers:
        ctype = controller.type
        actions = controller.actions or {}
        if not actions:
            continue
        lines.append(f"  {ctype.lower()}:")
        lines.append("    actions:")
        for key, action in actions.items():
            lines.append(f'      "{key}":')
            title = (action.get("States") or [{}])[0].get("Title", "")
            if title:
                lines.append(f"        title: {title}")
            icon = action.get("Icon") or action.get("Encoder", {}).get("Icon", "")
            if icon:
                lines.append(f"        icon: {icon}")
    return "\n".join(lines) + "\n"
