"""High-level read-only listing helpers used by the `list-*` CLI commands."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from streamdeck_cli.manifest import (
    Device,
    Profile,
    find_profile_dirs,
    load_page,
    load_profile,
)


@dataclass(frozen=True)
class PageListing:
    """Page summary for ``list-pages`` — what the user actually sees."""

    uuid: str
    name: str
    is_current: bool
    is_default: bool


def list_devices(root: Path) -> list[Device]:
    """One ``Device`` per ``.sdProfile`` directory under the install root."""
    out: list[Device] = []
    for pdir in find_profile_dirs(root):
        profile = load_profile(pdir)
        out.append(profile.device)
    return out


def list_profiles(root: Path) -> list[Profile]:
    """One ``Profile`` per ``.sdProfile`` directory."""
    return [load_profile(p) for p in find_profile_dirs(root)]


def list_pages(profile_dir: Path) -> list[PageListing]:
    """Active pages for the given profile, in the order they appear in the manifest."""
    profile = load_profile(profile_dir)
    pages_dir = profile_dir / "Profiles"
    out: list[PageListing] = []
    for uuid in profile.pages.active:
        page_dir = pages_dir / uuid
        if not page_dir.is_dir():
            continue
        page = load_page(page_dir)
        out.append(
            PageListing(
                uuid=uuid,
                name=page.name,
                is_current=(uuid == profile.pages.current),
                is_default=(uuid == profile.pages.default),
            )
        )
    return out
