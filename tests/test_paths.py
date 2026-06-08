"""Tests for the path resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from streamdeck_cli.paths import ProfileRoot, default_profile_root, resolve_profile_root
from tests.conftest import REAL_PROFILE_ROOT as FIXTURES


class TestDefaultProfileRoot:
    def test_returns_mac_path_when_run_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("streamdeck_cli.paths.platform.system", lambda: "Darwin")
        result = default_profile_root()
        assert result == Path.home() / "Library" / "Application Support" / "com.elgato.StreamDeck"

    def test_returns_windows_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("streamdeck_cli.paths.platform.system", lambda: "Windows")
        monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
        result = default_profile_root()
        assert result == Path("C:/Users/test/AppData/Roaming") / "Elgato" / "StreamDeck"

    def test_unsupported_platform_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("streamdeck_cli.paths.platform.system", lambda: "Plan9")
        with pytest.raises(NotImplementedError, match="Plan9"):
            default_profile_root()


class TestResolveProfileRoot:
    def test_explicit_path_is_returned_unchanged(self, tmp_path: Path) -> None:
        result = resolve_profile_root(tmp_path)
        assert result == ProfileRoot(root=tmp_path, exists=True)

    def test_default_path_uses_system_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("streamdeck_cli.paths.platform.system", lambda: "Darwin")
        result = resolve_profile_root()
        assert result.root == Path.home() / "Library" / "Application Support" / "com.elgato.StreamDeck"

    def test_existing_path_marks_exists_true(self, tmp_path: Path) -> None:
        result = resolve_profile_root(tmp_path)
        assert result.exists is True

    def test_missing_path_marks_exists_false(self, tmp_path: Path) -> None:
        result = resolve_profile_root(tmp_path / "does-not-exist")
        assert result.exists is False


class TestProfileRootProfilesDir:
    def test_profiles_dir_is_profilesv3(self) -> None:
        root = ProfileRoot(root=FIXTURES, exists=True)
        assert root.profiles_dir == FIXTURES / "ProfilesV3"

    def test_profiles_dir_does_not_create_disk(self, tmp_path: Path) -> None:
        root = ProfileRoot(root=tmp_path, exists=False)
        assert (root.profiles_dir.exists()) is False
        assert root.profiles_dir == tmp_path / "ProfilesV3"
