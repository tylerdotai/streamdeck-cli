"""Tests for the listing commands."""
from __future__ import annotations

from streamdeck_cli.listing import list_devices, list_pages, list_profiles
from tests.conftest import PROFILE_DIR
from tests.conftest import REAL_PROFILE_ROOT as FIXTURES


class TestListDevices:
    def test_returns_device_with_model(self) -> None:
        devices = list_devices(FIXTURES)
        assert len(devices) == 1
        assert devices[0].model == "20GBD9901"
        assert "XL" in devices[0].device_class() or "Stream Deck" in devices[0].device_class()


class TestListProfiles:
    def test_returns_one_profile(self) -> None:
        profiles = list_profiles(FIXTURES)
        assert len(profiles) == 1
        assert profiles[0].name == "Default Profile"


class TestListPages:
    def test_returns_two_active_pages(self) -> None:
        pages = list_pages(PROFILE_DIR)
        assert len(pages) == 2

    def test_pages_have_uuid(self) -> None:
        pages = list_pages(PROFILE_DIR)
        for p in pages:
            assert p.uuid
            assert "-" in p.uuid
            assert len(p.uuid) == 36
