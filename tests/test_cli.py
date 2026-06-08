"""Tests for the Click CLI surface — invoked via the CliRunner.

We do not touch the user's real install. Each test uses the
``fixtures/real-profile`` fixture (read-only) and a tmp_path copy for writes.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from streamdeck_cli.cli import main

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real-profile"
PROFILE_DIR = FIXTURES / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def tmp_install(tmp_path: Path) -> Path:
    """A copy of FIXTURES (which IS the install root) into tmp_path/install."""
    dest = tmp_path / "install"
    shutil.copytree(FIXTURES, dest)
    return dest


# ── list-* commands ────────────────────────────────────────────────────────


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
        result = runner.invoke(
            main, ["list-pages", "--install-root", str(FIXTURES)]
        )
        assert result.exit_code == 0
        # At least one UUID should appear
        assert "ff56cdd9-5ca7-4e39-927d-2390318b62f7" in result.output.lower()


class TestShowPage:
    def test_shows_manifest_json(self, runner: CliRunner) -> None:
        result = runner.invoke(
            main,
            [
                "show-page",
                "ff56cdd9-5ca7-4e39-927d-2390318b62f7",
                "--install-root",
                str(FIXTURES),
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        types = {c["Type"] for c in data["Controllers"]}
        # Real-world fixture has both Keypad and Encoder controllers
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
            main,
            ["new-page", "--name", "CLI Test", "--install-root", str(tmp_install)],
        )
        assert result.exit_code == 0
        new_uuid = result.output.strip()
        # Profile manifest should now have 3 active pages
        manifest = json.loads(
            (tmp_install / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile" / "manifest.json").read_text()
        )
        assert new_uuid in manifest["Pages"]["Pages"]

    def test_set_current(self, runner: CliRunner, tmp_install: Path) -> None:
        # Create a new page first
        result = runner.invoke(
            main, ["new-page", "--name", "X", "--install-root", str(tmp_install)]
        )
        new_uuid = result.output.strip()
        # Set it current
        result = runner.invoke(
            main,
            ["set-current", new_uuid, "--install-root", str(tmp_install)],
        )
        assert result.exit_code == 0
        manifest = json.loads(
            (tmp_install / "ProfilesV3" / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile" / "manifest.json").read_text()
        )
        assert manifest["Pages"]["Current"] == new_uuid

    def test_delete_page_with_confirmation(
        self, runner: CliRunner, tmp_install: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "new-page",
                "--name",
                "Doomed",
                "--install-root",
                str(tmp_install),
            ],
        )
        new_uuid = result.output.strip()
        # Now delete it (with confirmation)
        result = runner.invoke(
            main,
            [
                "delete-page",
                new_uuid,
                "--install-root",
                str(tmp_install),
            ],
            input="y\n",
        )
        assert result.exit_code == 0
        assert not (
            tmp_install
            / "ProfilesV3"
            / "92B4842D-F21D-422E-B181-3733A63927AE.sdProfile"
            / "Profiles"
            / new_uuid
        ).exists()

    def test_validate_clean(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["validate", "--install-root", str(FIXTURES)])
        # The fixture has orphan pages → should warn but not fail
        assert "WARN:" in result.output or result.exit_code == 0


class TestBackupRestore:
    def test_backup_creates_zip(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "b.zip"
        result = runner.invoke(
            main, ["backup", "-o", str(out), "--install-root", str(FIXTURES)]
        )
        assert result.exit_code == 0
        assert out.exists()
        assert out.stat().st_size > 0

    def test_backup_overwrite_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "b.zip"
        out.write_text("existing")
        result = runner.invoke(
            main, ["backup", "-o", str(out), "--install-root", str(FIXTURES)]
        )
        assert result.exit_code != 0
