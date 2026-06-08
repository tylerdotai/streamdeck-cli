"""Sanitize a captured Stream Deck profile by replacing all UUIDs with stable
deterministic values and stripping image binaries.

The output is committed to the repo as a public test fixture. It contains
the structure (page layout, action schemas, controller types) but not the
user's device IDs, icon data, or any personally identifying information.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path


def sanitize_uuids(obj: object, mapping: dict[str, str]) -> object:
    """Recursively replace known UUIDs in a JSON-compatible structure."""
    if isinstance(obj, str):
        if obj in mapping:
            return mapping[obj]
        # Match common UUID patterns (with or without curly braces)
        if len(obj) == 36 and obj.count("-") == 4:
            mapped = mapping.get(obj)
            if mapped is not None:
                return mapped
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_uuids(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_uuids(v, mapping) for v in obj]
    return obj


def make_stable_uuid(seed: str) -> str:
    """Generate a deterministic UUID-shaped string from a seed."""
    h = hashlib.sha256(seed.encode()).hexdigest().upper()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def sanitize_profile_dir(profile_dir: Path, profile_seed: str) -> None:
    """Sanitize a .sdProfile directory in place."""
    # Read the profile manifest and build a UUID → sanitized UUID map
    manifest_path = profile_dir / "manifest.json"
    data = json.loads(manifest_path.read_text())

    # Collect all UUIDs that appear
    all_uuids: set[str] = set()
    pages = data.get("Pages", {})
    all_uuids.add(pages.get("Current", ""))
    all_uuids.add(pages.get("Default", ""))
    for p in pages.get("Pages", []):
        all_uuids.add(p)

    # Also collect page subdirs on disk
    pages_dir = profile_dir / "Profiles"
    if pages_dir.exists():
        for entry in pages_dir.iterdir():
            if entry.is_dir():
                all_uuids.add(entry.name)

    # Filter out empty strings
    all_uuids.discard("")

    # Build a deterministic, order-stable mapping. Sort by *role* first so
    # the "current" page always gets mapping[0], the "default" page always
    # gets mapping[1], etc. This keeps the on-disk rename deterministic
    # and ensures the test fixtures' hardcoded UUIDs work.
    ordered: list[str] = []
    for role in (pages.get("Current"), pages.get("Default")):
        if role and role not in ordered:
            ordered.append(role)
    for p in pages.get("Pages", []):
        if p and p not in ordered:
            ordered.append(p)
    # Add any remaining (orphan dirs) in sorted order
    for u in sorted(all_uuids):
        if u not in ordered:
            ordered.append(u)

    mapping: dict[str, str] = {}
    for i, uuid in enumerate(ordered):
        mapping[uuid] = make_stable_uuid(f"{profile_seed}:page:{i}")

    # Replace the device UUID too
    device = data.get("Device", {})
    if "UUID" in device:
        device["UUID"] = f"@(1)[sanitized/000/{make_stable_uuid(profile_seed)[:13]}]"

    # Sanitize the manifest JSON
    sanitized = sanitize_uuids(data, mapping)
    manifest_path.write_text(json.dumps(sanitized, indent=4))

    # Rename page subdirs on disk to match the new UUIDs
    if pages_dir.exists():
        for old_name, new_name in mapping.items():
            old_dir = pages_dir / old_name
            new_dir = pages_dir / new_name
            if old_dir.is_dir() and not new_dir.exists():
                old_dir.rename(new_dir)

    # Sanitize each page's manifest
    if pages_dir.exists():
        for page_dir in pages_dir.iterdir():
            if not page_dir.is_dir():
                continue
            page_manifest_path = page_dir / "manifest.json"
            if page_manifest_path.exists():
                page_data = json.loads(page_manifest_path.read_text())
                page_data = sanitize_uuids(page_data, mapping)
                page_manifest_path.write_text(json.dumps(page_data, indent=4))

            # Strip all images
            images_dir = page_dir / "Images"
            if images_dir.exists():
                shutil.rmtree(images_dir)

    # Remove plugin-specific UUID references that don't make sense in a sanitized context
    # (we keep them, they're just opaque IDs)


def sanitize_install_root(src: Path, dest: Path, profile_seed: str = "default") -> Path:
    """Sanitize an entire install root into ``dest``.

    ``src`` is the install root (contains ``ProfilesV3/``). Only the
    ``ProfilesV3/`` subdir is copied — plugins, backups, marketplace, etc.
    are skipped.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    src_profiles = src / "ProfilesV3"
    if not src_profiles.is_dir():
        raise FileNotFoundError(f"no ProfilesV3/ under {src}")

    dest_profiles = dest / "ProfilesV3"
    shutil.copytree(src_profiles, dest_profiles)

    profiles_v3 = dest / "ProfilesV3"
    for entry in profiles_v3.iterdir():
        if entry.is_dir() and entry.suffix == ".sdProfile":
            # Rename the profile dir to a deterministic UUID
            new_profile_name = f"{make_stable_uuid(f'profile:{profile_seed}')}.sdProfile"
            entry.rename(entry.parent / new_profile_name)
            sanitize_profile_dir(entry.parent / new_profile_name, profile_seed)
    return dest


if __name__ == "__main__":
    src = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "/Users/soup/Library/Application Support/com.elgato.StreamDeck"
    )
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else "fixtures/real-profile")
    out = sanitize_install_root(src, dest)
    print(f"sanitized profile written to {out}")
