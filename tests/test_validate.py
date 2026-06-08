"""Tests for the validate command."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from streamdeck_cli.validate import validate_page, validate_profile
from tests.conftest import PROFILE_DIR


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


class TestValidateProfile:
    def test_valid_profile_passes(self, isolated_profile: Path) -> None:
        result = validate_profile(isolated_profile)
        assert result.ok
        assert result.errors == []

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        result = validate_profile(tmp_path / "nope.sdProfile")
        assert not result.ok
        assert any("manifest" in e.lower() for e in result.errors)

    def test_orphan_page_dir_warns(self, isolated_profile: Path) -> None:
        orphan = isolated_profile / "Profiles" / "00000000-0000-0000-0000-000000000000"
        orphan.mkdir()
        result = validate_profile(isolated_profile)
        assert any("orphan" in w.lower() for w in result.warnings)

    def test_current_page_missing_fails(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        current = manifest["Pages"]["Current"]
        page_dir = isolated_profile / "Profiles" / current
        if page_dir.exists():
            shutil.rmtree(page_dir)
        result = validate_profile(isolated_profile)
        assert not result.ok
        assert any("current" in e.lower() for e in result.errors)


class TestValidatePage:
    def test_valid_empty_page_passes(self, isolated_profile: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "E3B4A4C1-F629-88D7-DCE5-CE8C672C96FB"
        result = validate_page(page_dir)
        assert result.ok

    def test_valid_populated_page_passes(self, isolated_profile: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        result = validate_page(page_dir)
        assert result.ok

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            validate_page(tmp_path)
