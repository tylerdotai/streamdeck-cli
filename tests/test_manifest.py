"""Tests for the manifest dataclasses."""
from __future__ import annotations

import json
from pathlib import Path

from streamdeck_cli.manifest import (
    Profile,
    load_page,
    load_profile_from_root,
)
from tests.conftest import PROFILE_DIR


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
        assert profile.device.uuid.startswith("@(1)[sanitized")

    def test_lists_pages(self) -> None:
        manifest = _read_json(PROFILE_DIR / "manifest.json")
        profile = Profile.from_dict(manifest, path=PROFILE_DIR)
        assert len(profile.pages.active) == 2
        assert profile.pages.current in profile.pages.active
        assert profile.pages.default not in profile.pages.active

    def test_load_profile_from_root_uses_first_sdprofile(self) -> None:
        from tests.conftest import REAL_PROFILE_ROOT
        profile = load_profile_from_root(REAL_PROFILE_ROOT)
        assert profile.name == "Default Profile"
        assert profile.device.model == "20GBD9901"


class TestLoadPage:
    def test_loads_empty_page(self) -> None:
        # E6C9ECAB is the default page in the sanitized fixture
        page_dir = PROFILE_DIR / "Profiles" / "E3B4A4C1-F629-88D7-DCE5-CE8C672C96FB"
        page = load_page(page_dir)
        assert len(page.controllers) == 2
        types = {c.type for c in page.controllers}
        assert types == {"Keypad", "Encoder"}

    def test_loads_populated_page(self) -> None:
        # D527A48C is the current page
        page_dir = PROFILE_DIR / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        page = load_page(page_dir)
        keypad = next(c for c in page.controllers if c.type == "Keypad")
        assert keypad.actions is not None
        assert len(keypad.actions) > 0
        first_key = next(iter(keypad.actions.keys()))
        assert "," in first_key


class TestPageRoundTrip:
    def test_empty_page_round_trips(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "E3B4A4C1-F629-88D7-DCE5-CE8C672C96FB"
        page = load_page(page_dir)
        data = page.to_dict()
        assert [c["Type"] for c in data["Controllers"]] == [c.type for c in page.controllers]
        assert data["Icon"] == ""
        assert data["Name"] == ""

    def test_populated_page_round_trips(self) -> None:
        page_dir = PROFILE_DIR / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        original = _read_json(page_dir / "manifest.json")
        page = load_page(page_dir)
        data = page.to_dict()
        assert set(data.keys()) == set(original.keys())
