"""Tests for the manifest dataclasses — the reverse-engineered schema for the
Stream Deck 7.x on-disk JSON format.

Fixtures under ``fixtures/real-profile/`` were captured from a real install
and are shaped like the install root: ``ProfilesV3/<uuid>.sdProfile/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from streamdeck_cli.manifest import (
    Profile,
    load_page,
    load_profile_from_root,
)

# Fixture root is the install root.
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real-profile"
PROFILE_DIR = FIXTURES / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile"


def _read_json(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


class TestLoadProfile:
    def test_loads_default_profile(self) -> None:
        manifest = _read_json(PROFILE_DIR / "manifest.json")
        profile = Profile.from_dict(manifest, path=PROFILE_DIR)
        assert profile.name == "Default Profile"
        assert profile.version == "3.0"
        assert profile.device.model == "20GBD9901"
        assert profile.device.uuid.startswith("@(1)[")

    def test_lists_pages(self) -> None:
        manifest = _read_json(PROFILE_DIR / "manifest.json")
        profile = Profile.from_dict(manifest, path=PROFILE_DIR)
        # The fixture's manifest declares 2 active pages (the other 4 subdirs on disk are orphans).
        assert len(profile.pages.active) == 2
        assert profile.pages.current in profile.pages.active
        assert profile.pages.default not in profile.pages.active  # default was replaced by newer pages

    def test_load_profile_from_root_uses_first_sdprofile(self) -> None:
        profile = load_profile_from_root(FIXTURES)
        assert profile.name == "Default Profile"
        assert profile.device.model == "20GBD9901"


class TestLoadPage:
    def test_loads_empty_page(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "8DBCFF3D-E4D6-45EE-881D-1ED8016C300B"
        page = load_page(page_dir)
        assert page.name == ""
        assert page.icon == ""
        assert len(page.controllers) == 2
        # Stream Deck may emit Controllers in either order
        types = {c.type for c in page.controllers}
        assert types == {"Keypad", "Encoder"}
        keypad = next(c for c in page.controllers if c.type == "Keypad")
        assert keypad.actions is None

    def test_loads_populated_page(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "FF56CDD9-5CA7-4E39-927D-2390318B62F7"
        page = load_page(page_dir)
        # It's the current page; it should have actions configured
        keypad = next(c for c in page.controllers if c.type == "Keypad")
        assert keypad.actions is not None
        # There should be at least one action on the keypad grid.
        assert len(keypad.actions) > 0
        # Action keys are coordinates like "0,0", "1,0", etc.
        first_key = next(iter(keypad.actions.keys()))
        assert "," in first_key
        col, row = map(int, first_key.split(","))
        assert col >= 0
        assert row >= 0


class TestPageRoundTrip:
    def test_empty_page_round_trips(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "8DBCFF3D-E4D6-45EE-881D-1ED8016C300B"
        page = load_page(page_dir)
        data = page.to_dict()
        # Controllers must keep their order from the original
        assert [c["Type"] for c in data["Controllers"]] == [c.type for c in page.controllers]
        assert data["Icon"] == ""
        assert data["Name"] == ""

    def test_populated_page_round_trips(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "FF56CDD9-5CA7-4E39-927D-2390318B62F7"
        original = _read_json(page_dir / "manifest.json")
        page = load_page(page_dir)
        data = page.to_dict()
        # Top-level keys must match the original set.
        assert set(data.keys()) == set(original.keys())
        # Controller types preserved.
        assert [c["Type"] for c in data["Controllers"]] == [
            c["Type"] for c in original["Controllers"]
        ]
