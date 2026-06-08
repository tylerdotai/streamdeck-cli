"""Tests for the `validate` command — catches manifest corruption before the SD app sees it."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from streamdeck_cli.validate import validate_page, validate_profile

# Fixture is the install root.
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real-profile"
PROFILE_DIR = FIXTURES / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile"


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    """Copy the real fixture's profile dir into tmp so tests can mutate it safely."""
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


class TestValidateProfile:
    def test_valid_profile_passes(self, isolated_profile: Path) -> None:
        result = validate_profile(isolated_profile)
        assert result.ok
        assert result.errors == []

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        # Empty profile root → no manifest.json
        result = validate_profile(tmp_path / "nope.sdProfile")
        assert not result.ok
        assert any("manifest" in e.lower() for e in result.errors)

    def test_orphan_page_dir_warns(self, isolated_profile: Path) -> None:
        # Add an empty dir under Profiles that isn't referenced in manifest
        orphan = isolated_profile / "Profiles" / "00000000-0000-0000-0000-000000000000"
        orphan.mkdir()
        result = validate_profile(isolated_profile)
        assert any("orphan" in w.lower() for w in result.warnings)

    def test_current_page_missing_fails(self, isolated_profile: Path) -> None:
        # Remove the page that manifest points to as Current
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        current = manifest["Pages"]["Current"]
        page_dir = isolated_profile / "Profiles" / current.upper()
        if page_dir.exists():
            shutil.rmtree(page_dir)
        result = validate_profile(isolated_profile)
        assert not result.ok
        assert any("current" in e.lower() for e in result.errors)


class TestValidatePage:
    def test_valid_empty_page_passes(self, isolated_profile: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "8DBCFF3D-E4D6-45EE-881D-1ED8016C300B"
        result = validate_page(page_dir)
        assert result.ok

    def test_valid_populated_page_passes(self, isolated_profile: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "FF56CDD9-5CA7-4E39-927D-2390318B62F7"
        result = validate_page(page_dir)
        assert result.ok

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            validate_page(tmp_path)
