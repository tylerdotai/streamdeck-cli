"""Tests for the CLI surface."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from streamdeck_cli.cli import main
from tests.conftest import PROFILE_DIR
from tests.conftest import REAL_PROFILE_ROOT as FIXTURES


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def tmp_install(tmp_path: Path) -> Path:
    dest = tmp_path / "install"
    shutil.copytree(FIXTURES, dest)
    return dest


class TestListCommands:
    def test_list_devices(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["list-devices", "--install-root", str(FIXTURES)])
        assert result.exit_code == 0
        assert "20GBD9901" in result.output
        assert "Stream Deck XL" in result.output

    def test_list_profiles(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["list-profiles", "--install-root", str(FIXTURES)])
        assert result.exit_code == 0
        assert "Default Profile" in result.output

    def test_list_pages(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["list-pages", "--install-root", str(FIXTURES)])
        assert result.exit_code == 0
        # At least one UUID should appear (case-insensitive)
        assert any(c in result.output for c in ["d527a48c-1eba-0eac-2c19-c1bb0b353034", "ABE23767-B7E5-62B5-C463-F3D5D64CB922"])


class TestShowPage:
    def test_shows_manifest_json(self, runner: CliRunner) -> None:
        result = runner.invoke(
            main,
            [
                "show-page",
                "abe23767-b7e5-62b5-c463-f3d5d64cb922",
                "--install-root",
                str(FIXTURES),
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        types = {c["Type"] for c in data["Controllers"]}
        assert types == {"Keypad", "Encoder"}

    def test_unknown_page_errors(self, runner: CliRunner) -> None:
        result = runner.invoke(
            main,
            [
                "show-page",
                "00000000-0000-0000-0000-000000000000",
                "--install-root",
                str(FIXTURES),
            ],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestWriteCommands:
    def test_new_page(self, runner: CliRunner, tmp_install: Path) -> None:
        result = runner.invoke(
            main, ["new-page", "--name", "CLI Test", "--install-root", str(tmp_install)]
        )
        assert result.exit_code == 0, result.output
        new_uuid = result.output.strip()
        manifest = json.loads(
            (tmp_install / "ProfilesV3" / PROFILE_DIR.name / "manifest.json").read_text()
        )
        assert new_uuid in manifest["Pages"]["Pages"]

    def test_set_current(self, runner: CliRunner, tmp_install: Path) -> None:
        result = runner.invoke(
            main, ["new-page", "--name", "X", "--install-root", str(tmp_install)]
        )
        new_uuid = result.output.strip()
        result = runner.invoke(
            main, ["set-current", new_uuid, "--install-root", str(tmp_install)]
        )
        assert result.exit_code == 0
        manifest = json.loads(
            (tmp_install / "ProfilesV3" / PROFILE_DIR.name / "manifest.json").read_text()
        )
        assert manifest["Pages"]["Current"] == new_uuid

    def test_delete_page_with_confirmation(self, runner: CliRunner, tmp_install: Path) -> None:
        result = runner.invoke(
            main, ["new-page", "--name", "Doomed", "--install-root", str(tmp_install)]
        )
        new_uuid = result.output.strip()
        result = runner.invoke(
            main,
            ["delete-page", new_uuid, "--install-root", str(tmp_install)],
            input="y\n",
        )
        assert result.exit_code == 0, result.output
        assert not (tmp_install / "ProfilesV3" / PROFILE_DIR.name / "Profiles" / new_uuid).exists()

    def test_validate_clean(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["validate", "--install-root", str(FIXTURES)])
        # Sanitized fixture has orphan pages, so expect warnings or a successful exit
        assert "WARN:" in result.output or result.exit_code == 0


class TestBackupRestore:
    def test_backup_creates_zip(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "b.zip"
        result = runner.invoke(main, ["backup", "-o", str(out), "--install-root", str(FIXTURES)])
        assert result.exit_code == 0
        assert out.exists()
        assert out.stat().st_size > 0

    def test_backup_overwrite_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "b.zip"
        out.write_text("existing")
        result = runner.invoke(main, ["backup", "-o", str(out), "--install-root", str(FIXTURES)])
        assert result.exit_code != 0
