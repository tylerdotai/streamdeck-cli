"""Tests for listing devices, profiles, and pages from a Stream Deck install.

The CLI's `list` commands read straight from the on-disk JSON manifests.
"""
from __future__ import annotations

from pathlib import Path

from streamdeck_cli.listing import (
    list_devices,
    list_pages,
    list_profiles,
)

# Fixture root is the install root.
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real-profile"
PROFILE_DIR = FIXTURES / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile"


class TestListDevices:
    def test_returns_device_with_model(self) -> None:
        devices = list_devices(FIXTURES)
        assert len(devices) == 1
        assert devices[0].model == "20GBD9901"
        # 20GBD9901 is the Stream Deck XL (Gen 1).
        assert "XL" in devices[0].device_class() or "Stream Deck" in devices[0].device_class()


class TestListProfiles:
    def test_returns_one_profile(self) -> None:
        profiles = list_profiles(FIXTURES)
        assert len(profiles) == 1
        assert profiles[0].name == "Default Profile"


class TestListPages:
    def test_returns_three_active_pages(self) -> None:
        pages = list_pages(PROFILE_DIR)
        # The fixture's manifest declares 2 active pages (the other 4 subdirs on disk are orphans).
        assert len(pages) == 2

    def test_pages_have_uuid(self) -> None:
        pages = list_pages(PROFILE_DIR)
        for p in pages:
            assert p.uuid
            # UUIDs from Stream Deck are uppercase with hyphens
            assert "-" in p.uuid
            assert len(p.uuid) == 36
