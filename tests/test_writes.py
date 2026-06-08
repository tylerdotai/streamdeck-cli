"""Tests for page writes."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from streamdeck_cli.writes import (
    backup_profile,
    clone_page,
    create_page,
    delete_page,
    restore_profile,
    set_current_page,
)
from tests.conftest import PROFILE_DIR


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


class TestCreatePage:
    def test_creates_page_directory_and_manifest(self, isolated_profile: Path) -> None:
        new_uuid = create_page(isolated_profile, name="Test Page", icon="")
        assert "-" in new_uuid
        assert len(new_uuid) == 36
        page_dir = isolated_profile / "Profiles" / new_uuid
        assert page_dir.is_dir()
        manifest = json.loads((page_dir / "manifest.json").read_text())
        assert manifest["Name"] == "Test Page"
        types = {c["Type"] for c in manifest["Controllers"]}
        assert types == {"Keypad", "Encoder"}

    def test_registers_page_in_profile_manifest(self, isolated_profile: Path) -> None:
        before = json.loads((isolated_profile / "manifest.json").read_text())
        new_uuid = create_page(isolated_profile, name="Registered")
        after = json.loads((isolated_profile / "manifest.json").read_text())
        assert len(after["Pages"]["Pages"]) == len(before["Pages"]["Pages"]) + 1
        assert new_uuid in after["Pages"]["Pages"]


class TestClonePage:
    def test_clones_page_into_new_uuid(self, isolated_profile: Path) -> None:
        source = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        new_uuid = clone_page(isolated_profile, source, new_name="Cloned Page")
        assert new_uuid != source
        new_dir = isolated_profile / "Profiles" / new_uuid
        assert new_dir.is_dir()
        manifest = json.loads((new_dir / "manifest.json").read_text())
        assert manifest["Name"] == "Cloned Page"

    def test_unknown_source_raises(self, isolated_profile: Path) -> None:
        with pytest.raises(FileNotFoundError, match="source page not found"):
            clone_page(isolated_profile, "00000000-0000-0000-0000-000000000000")


class TestDeletePage:
    def test_deletes_page_directory(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        target = next(
            uuid
            for uuid in manifest["Pages"]["Pages"]
            if uuid != manifest["Pages"]["Current"]
            and uuid != manifest["Pages"]["Default"]
        )
        page_dir = isolated_profile / "Profiles" / target
        assert page_dir.is_dir()
        delete_page(isolated_profile, target)
        assert not page_dir.exists()

    def test_removes_from_profile_manifest(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        target = next(
            uuid
            for uuid in manifest["Pages"]["Pages"]
            if uuid != manifest["Pages"]["Current"]
            and uuid != manifest["Pages"]["Default"]
        )
        delete_page(isolated_profile, target)
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        assert target not in manifest["Pages"]["Pages"]

    def test_cannot_delete_current_page(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        current = manifest["Pages"]["Current"]
        with pytest.raises(ValueError, match="current page"):
            delete_page(isolated_profile, current)

    def test_cannot_delete_default_page(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        default = manifest["Pages"]["Default"]
        if default not in manifest["Pages"]["Pages"]:
            manifest["Pages"]["Pages"].append(default)
        (isolated_profile / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="default page"):
            delete_page(isolated_profile, default)

    def test_unknown_page_raises(self, isolated_profile: Path) -> None:
        with pytest.raises(FileNotFoundError, match="page not found"):
            delete_page(isolated_profile, "00000000-0000-0000-0000-000000000000")


class TestSetCurrentPage:
    def test_changes_current_uuid(self, isolated_profile: Path) -> None:
        manifest = json.loads((isolated_profile / "manifest.json").read_text())
        target = next(
            uuid
            for uuid in manifest["Pages"]["Pages"]
            if uuid != manifest["Pages"]["Current"]
        )
        set_current_page(isolated_profile, target)
        after = json.loads((isolated_profile / "manifest.json").read_text())
        assert after["Pages"]["Current"] == target

    def test_unknown_page_raises(self, isolated_profile: Path) -> None:
        with pytest.raises(ValueError, match="not active"):
            set_current_page(isolated_profile, "00000000-0000-0000-0000-000000000000")


class TestBackupRestore:
    def test_backup_creates_zip(self, isolated_profile: Path, tmp_path: Path) -> None:
        out = backup_profile(isolated_profile, dest=tmp_path / "backup.zip")
        assert out.exists()
        assert out.stat().st_size > 0
        with out.open("rb") as fh:
            assert fh.read(2) == b"PK"

    def test_restore_replaces_profile(self, isolated_profile: Path, tmp_path: Path) -> None:
        install_root = tmp_path / "install"
        install_root.mkdir()
        profiles_v3 = install_root / "ProfilesV3"
        profiles_v3.mkdir()
        profile_copy = profiles_v3 / isolated_profile.name
        shutil.copytree(isolated_profile, profile_copy)

        create_page(profile_copy, name="Before Backup")
        zip_path = backup_profile(profile_copy, dest=tmp_path / "backup.zip")
        create_page(profile_copy, name="After Backup")
        restore_profile(zip_path, install_root)

        manifest = json.loads((profile_copy / "manifest.json").read_text())
        names = [
            json.loads((profile_copy / "Profiles" / uuid / "manifest.json").read_text())["Name"]
            for uuid in manifest["Pages"]["Pages"]
        ]
        assert "Before Backup" in names
        assert "After Backup" not in names
