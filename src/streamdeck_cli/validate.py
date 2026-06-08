"""Validate profile and page manifests.

Designed to be safe to run while the Stream Deck app is closed or while it's
running — it only reads. Use this to sanity-check a profile before/after
manipulation, or to find orphan page directories.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from streamdeck_cli.manifest import find_profile_dirs, load_page, load_profile


@dataclass
class ValidationResult:
    """Result of a validation pass."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # convenience: `if validate_profile(...)`
        return self.ok


def _page_dir_exists(pages_dir: Path, uuid_str: str) -> bool:
    """Return True if a page directory with this UUID exists (case-insensitive)."""
    target = uuid_str.lower()
    return any(p.name.lower() == target for p in pages_dir.iterdir() if p.is_dir())


def _validate_profile_impl(profile_dir: Path) -> ValidationResult:
    result = ValidationResult(ok=True)
    manifest_path = profile_dir / "manifest.json"
    if not manifest_path.is_file():
        result.ok = False
        result.errors.append(f"missing manifest at {manifest_path}")
        return result

    try:
        profile = load_profile(profile_dir)
    except Exception as e:  # JSON parse error, missing keys, etc.
        result.ok = False
        result.errors.append(f"failed to parse profile manifest: {e}")
        return result

    # Current and default must exist on disk (case-insensitive).
    pages_dir = profile_dir / "Profiles"
    if not _page_dir_exists(pages_dir, profile.pages.current):
        result.ok = False
        result.errors.append(
            f"current page {profile.pages.current!r} is not on disk"
        )
    if not _page_dir_exists(pages_dir, profile.pages.default):
        result.ok = False
        result.errors.append(
            f"default page {profile.pages.default!r} is not on disk"
        )

    # Every active page must have a directory on disk.
    for uuid in profile.pages.active:
        if not _page_dir_exists(pages_dir, uuid):
            result.ok = False
            result.errors.append(f"active page {uuid!r} is missing its directory")

    # Orphan warning: directories under Profiles that aren't active pages.
    if pages_dir.is_dir():
        for entry in pages_dir.iterdir():
            if entry.is_dir() and entry.name not in profile.pages.active:
                result.warnings.append(
                    f"orphan page directory {entry.name!r} (not in active pages list)"
                )

    return result


def validate_profile(root: Path) -> ValidationResult:
    """Validate every profile under ``root/ProfilesV3``. Returns the *worst* result.

    If the root is the install root, every profile is checked. If the root is
    a specific ``.sdProfile`` directory, only that one is checked.
    """
    # If caller passes the install root, iterate all .sdProfile dirs.
    if (root / "ProfilesV3").is_dir() and not root.name.endswith(".sdProfile"):
        results = [_validate_profile_impl(p) for p in find_profile_dirs(root)]
    elif root.suffix == ".sdProfile":
        results = [_validate_profile_impl(root)]
    else:
        # Treat as install root with no ProfilesV3
        result = ValidationResult(ok=False)
        result.errors.append(
            f"no ProfilesV3 directory under {root} and {root} is not a .sdProfile"
        )
        return result

    merged = ValidationResult(ok=all(r.ok for r in results))
    for r in results:
        merged.errors.extend(r.errors)
        merged.warnings.extend(r.warnings)
    return merged


def validate_page(page_dir: Path) -> ValidationResult:
    """Validate a single page manifest."""
    result = ValidationResult(ok=True)
    manifest_path = page_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest at {manifest_path}")
    try:
        load_page(page_dir)
    except Exception as e:
        result.ok = False
        result.errors.append(f"failed to parse page manifest: {e}")
    return result
