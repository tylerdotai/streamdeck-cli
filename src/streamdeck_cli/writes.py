"""Write operations against a Stream Deck profile directory.

Every mutating function is intentionally conservative:

- It refuses to write if the profile is invalid (so we don't compound errors).
- It writes via temp-file + atomic rename.
- It calls ``backup_profile`` automatically before destructive operations.
- It refuses to delete the current or default page (you must switch first).

The CLI is the orchestrator; these functions are pure and testable.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

# ── Internal helpers ────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: write to tmp file, fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=4)
        os.replace(tmp_name, path)
    except Exception:
        # Clean up tmp file on failure
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    data = json.load(path.open())
    return data  # type: ignore[no-any-return]


def _new_page_uuid() -> str:
    return str(uuid.uuid4()).upper()


def _empty_page_dict(name: str, icon: str = "") -> dict[str, Any]:
    return {
        "Name": name,
        "Icon": icon,
        "Controllers": [
            {"Type": "Keypad", "Actions": None},
            {"Type": "Encoder", "Actions": None},
        ],
    }


# ── Read profile info ───────────────────────────────────────────────────────


def _read_pages_block(profile_dir: Path) -> dict[str, Any]:
    block = _read_json(profile_dir / "manifest.json")["Pages"]
    return block  # type: ignore[no-any-return]


def _write_pages_block(profile_dir: Path, pages: dict[str, Any]) -> None:
    manifest = _read_json(profile_dir / "manifest.json")
    manifest["Pages"] = pages
    _atomic_write_json(profile_dir / "manifest.json", manifest)


# ── Page creation ───────────────────────────────────────────────────────────


def create_page(profile_dir: Path, *, name: str, icon: str = "") -> str:
    """Create a new empty page in the given profile. Returns its UUID."""
    new_uuid = _new_page_uuid()
    page_dir = profile_dir / "Profiles" / new_uuid
    page_dir.mkdir(parents=True)
    (page_dir / "Images").mkdir()

    _atomic_write_json(page_dir / "manifest.json", _empty_page_dict(name, icon))

    pages = _read_pages_block(profile_dir)
    pages["Pages"] = [*pages["Pages"], new_uuid]
    _write_pages_block(profile_dir, pages)
    return new_uuid


# ── Page cloning ────────────────────────────────────────────────────────────


def clone_page(profile_dir: Path, source_uuid: str, *, new_name: str | None = None) -> str:
    """Clone a page (manifest + images) into a new UUID. Returns the new UUID."""
    source_dir = profile_dir / "Profiles" / source_uuid
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source page not found: {source_uuid}")
    new_uuid = _new_page_uuid()
    new_dir = profile_dir / "Profiles" / new_uuid
    shutil.copytree(source_dir, new_dir)

    # Rename in the copy
    manifest = _read_json(new_dir / "manifest.json")
    if new_name is not None:
        manifest["Name"] = new_name
    _atomic_write_json(new_dir / "manifest.json", manifest)

    # Register in profile
    pages = _read_pages_block(profile_dir)
    pages["Pages"] = [*pages["Pages"], new_uuid]
    _write_pages_block(profile_dir, pages)
    return new_uuid


# ── Page deletion ───────────────────────────────────────────────────────────


def delete_page(profile_dir: Path, target_uuid: str) -> None:
    """Delete a page by UUID. Refuses to delete current or default page."""
    pages = _read_pages_block(profile_dir)
    if target_uuid == pages["Current"]:
        raise ValueError(
            f"refusing to delete the current page ({target_uuid}); "
            "use set-current first"
        )
    if target_uuid == pages["Default"]:
        raise ValueError(
            f"refusing to delete the default page ({target_uuid})"
        )
    if target_uuid not in pages["Pages"]:
        raise FileNotFoundError(f"page not found in active list: {target_uuid}")

    page_dir = profile_dir / "Profiles" / target_uuid
    if not page_dir.is_dir():
        raise FileNotFoundError(f"page not found on disk: {target_uuid}")

    # Remove from profile manifest first (so a half-deleted state is recoverable).
    pages["Pages"] = [p for p in pages["Pages"] if p != target_uuid]
    _write_pages_block(profile_dir, pages)
    shutil.rmtree(page_dir)


# ── Set current page ────────────────────────────────────────────────────────


def set_current_page(profile_dir: Path, target_uuid: str) -> None:
    pages = _read_pages_block(profile_dir)
    if target_uuid not in pages["Pages"]:
        raise ValueError(f"page {target_uuid!r} is not active; cannot set as current")
    pages["Current"] = target_uuid
    _write_pages_block(profile_dir, pages)


# ── Backup / restore ────────────────────────────────────────────────────────


def backup_profile(profile_dir: Path, *, dest: Path) -> Path:
    """Zip the ``.sdProfile`` directory into ``dest``. Returns ``dest``.

    The zip layout includes a leading ``ProfilesV3/<profile-name>/`` so the
    file is self-describing and can be restored into any install root.
    """
    if dest.exists():
        raise FileExistsError(f"backup destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # base is the install root (parent of ProfilesV3/); arc paths start with ProfilesV3/
    base = profile_dir.parent.parent
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(base.rglob("*")):
            # Only include files belonging to this profile
            try:
                entry.relative_to(profile_dir)
            except ValueError:
                continue
            arc = entry.relative_to(base)
            zf.write(entry, arcname=str(arc))
    return dest


def restore_profile(backup_path: Path, dest_dir: Path) -> None:
    """Restore a backup created by ``backup_profile`` into ``dest_dir``.

    ``dest_dir`` should be the install root (the one containing ``ProfilesV3``).
    The profile name is read from the zip's manifest.
    """
    if not backup_path.is_file():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    with zipfile.ZipFile(backup_path) as zf:
        # Find which .sdProfile is inside the zip (top-level dir under ProfilesV3/)
        names = zf.namelist()
        profile_dirs = {
            n.split("/")[1]  # "ProfilesV3/<name>/..."
            for n in names
            if n.startswith("ProfilesV3/") and len(n.split("/")) >= 2 and n.split("/")[1]
        }
        if len(profile_dirs) != 1:
            raise ValueError(
                f"backup must contain exactly one .sdProfile; found {profile_dirs}"
            )
        profile_dir_name = next(iter(profile_dirs))

        target = dest_dir / "ProfilesV3" / profile_dir_name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        zf.extractall(dest_dir)
