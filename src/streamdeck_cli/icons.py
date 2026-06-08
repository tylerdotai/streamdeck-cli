"""Icon import — copy a PNG into a page's ``Images/`` dir and reference it from the action manifest.

Stream Deck icons live at ``<page>/Images/<32-char-id>.png`` and are referenced
from the action object as ``Icon: "Images/97WWHHJRAT34T7TC9VPFNTCCWOZ.png"`` (or
``Encoder.Icon`` for encoder row actions).

The filename is deterministic — derived from a SHA-256 of the PNG bytes — so
re-running set-icon with the same content produces the same filename, and
Stream Deck picks it up without a UUID shuffle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class IconError(ValueError):
    """Raised when an icon cannot be set."""


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _validate_png(path: Path) -> bytes:
    """Read the file, verify PNG magic, return bytes."""
    data = path.read_bytes()
    if not data.startswith(_PNG_MAGIC):
        raise IconError(f"{path} is not a PNG file")
    return data


def _deterministic_name(png_bytes: bytes) -> str:
    """Generate a stable 32-char PNG filename from the content hash."""
    return hashlib.sha256(png_bytes).hexdigest()[:32].upper() + ".png"


def _parse_key(key: str) -> tuple[str, str, str]:
    """Parse a key spec into (controller_type, col_or_empty, row).

    - ``"0,0"`` → (Keypad, "0", "0")
    - ``"0"``   → (Encoder, "",  "0")   (row-only, friendly shortcut)
    - anything else → IconError
    """
    parts = key.split(",")
    if len(parts) == 2:
        col, row = parts
        col = col.strip()
        row = row.strip()
        if not col.isdigit() or not row.isdigit():
            raise IconError(
                f"invalid key format {key!r}: expected 'col,row' (e.g. '0,0') for keypad"
            )
        return "Keypad", col, row
    if len(parts) == 1 and parts[0].strip().isdigit():
        return "Encoder", "", parts[0].strip()
    raise IconError(
        f"invalid key format {key!r}: expected 'col,row' for keypad or 'row' for encoder"
    )


def _ensure_action(
    controllers: list[dict],
    controller_type: str,
    col: str,
    row: str,
) -> dict:
    """Find or create the action object for a (controller, col, row) key.

    Mutates and returns the action dict in place.
    """
    controller = next((c for c in controllers if c["Type"] == controller_type), None)
    if controller is None:
        raise IconError(f"page has no {controller_type} controller")
    if controller.get("Actions") is None:
        controller["Actions"] = {}
    actions = controller["Actions"]
    if controller_type == "Keypad":
        key = f"{col},{row}"
        if key not in actions:
            actions[key] = {
                "ActionID": "00000000-0000-0000-0000-000000000000",
                "Name": "",
                "UUID": "com.elgato.streamdeck.system.hotkey",
                "Plugin": {
                    "Name": "Activate a Key Command",
                    "UUID": "com.elgato.streamdeck.system.hotkey",
                    "Version": "1.0",
                },
                "LinkedTitle": True,
                "State": 0,
                "States": [{"Title": ""}],
            }
        return actions[key], key
    # Encoder
    key = f"0,{row}"
    if key not in actions:
        actions[key] = {
            "ActionID": "00000000-0000-0000-0000-000000000000",
            "Name": "",
            "UUID": "com.elgato.streamdeck.system.hotkey",
            "Plugin": {
                "Name": "Activate a Key Command",
                "UUID": "com.elgato.streamdeck.system.hotkey",
                "Version": "1.0",
            },
            "LinkedTitle": True,
            "State": 0,
            "States": [{"Title": ""}],
            "Encoder": {"Icon": ""},
        }
    action = actions[key]
    if "Encoder" not in action:
        action["Encoder"] = {"Icon": ""}
    return action, key


def set_icon(page_dir: Path, key: str, png_path: Path) -> str:
    """Copy ``png_path`` into the page's ``Images/`` dir and reference it from the action.

    Returns the new icon filename (relative to the page, e.g. ``Images/AB...png``).

    Raises ``IconError`` for any failure (bad PNG, bad key, missing page).
    """
    page_dir = page_dir.resolve()
    if not page_dir.is_dir():
        raise IconError(f"page not found: {page_dir}")
    manifest_path = page_dir / "manifest.json"
    if not manifest_path.is_file():
        raise IconError(f"page manifest not found: {manifest_path}")

    png_bytes = _validate_png(png_path)
    images_dir = page_dir / "Images"
    images_dir.mkdir(exist_ok=True)

    filename = _deterministic_name(png_bytes)
    target = images_dir / filename
    if not target.exists():
        target.write_bytes(png_bytes)
    rel_path = f"Images/{filename}"

    # Update the action manifest
    controller_type, col, row = _parse_key(key)
    data = json.loads(manifest_path.read_text())
    action, _ = _ensure_action(data["Controllers"], controller_type, col, row)
    if controller_type == "Keypad":
        action["Icon"] = rel_path
    else:
        action["Encoder"]["Icon"] = rel_path

    manifest_path.write_text(json.dumps(data, indent=4))
    return rel_path


def remove_icon(page_dir: Path, key: str) -> bool:
    """Remove the icon reference from the action (keeps the PNG file on disk).

    Returns ``True`` if a reference was removed, ``False`` if there was no icon
    to remove.
    """
    controller_type, col, row = _parse_key(key)
    manifest_path = page_dir / "manifest.json"
    if not manifest_path.is_file():
        raise IconError(f"page manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text())
    controller = next((c for c in data["Controllers"] if c["Type"] == controller_type), None)
    if controller is None or not controller.get("Actions"):
        return False
    full_key = f"{col},{row}" if controller_type == "Keypad" else f"0,{row}"
    action = controller["Actions"].get(full_key)
    if action is None:
        return False
    if controller_type == "Keypad" and "Icon" in action:
        del action["Icon"]
        manifest_path.write_text(json.dumps(data, indent=4))
        return True
    if controller_type == "Encoder" and action.get("Encoder", {}).get("Icon"):
        del action["Encoder"]["Icon"]
        manifest_path.write_text(json.dumps(data, indent=4))
        return True
    return False


def list_icons(page_dir: Path) -> dict[str, str]:
    """List all icons in a page: {key: "Images/foo.png"}.

    Keys are in ``"col,row"`` form for keypad, ``"0,row"`` for encoder.
    """
    manifest_path = page_dir / "manifest.json"
    if not manifest_path.is_file():
        raise IconError(f"page manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text())
    out: dict[str, str] = {}
    for controller in data.get("Controllers", []):
        actions = controller.get("Actions") or {}
        for key, action in actions.items():
            if controller["Type"] == "Keypad":
                icon = action.get("Icon")
                if icon:
                    out[key] = icon
            elif controller["Type"] == "Encoder":
                enc = action.get("Encoder", {})
                if enc.get("Icon"):
                    out[key] = enc["Icon"]
    return out
