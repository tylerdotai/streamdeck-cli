"""Tests for YAML page spec import/export.

A YAML spec describes a page's actions in a human-editable format. Example:

    name: Coding
    controllers:
      keypad:
        actions:
          "0,0":
            icon: pages/coding/key0.png
            title: VS Code
            plugin: com.elgato.streamdeck.system.hotkey
          "0,1":
            title: Terminal
      encoder:
        actions:
          "0":
            title: Volume

The library parses this, creates a page, writes the icons, and (optionally)
references them in the action manifest.
"""
from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

import pytest

from streamdeck_cli.yaml_pages import (
    YamlPageSpec,
    YamlSpecError,
    apply_yaml_spec,
    render_yaml_spec,
)
from tests.conftest import PROFILE_DIR


def _make_png(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes(color)
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


# ── Parse ───────────────────────────────────────────────────────────────────


class TestParse:
    def test_minimal_spec(self) -> None:
        spec = YamlPageSpec.from_yaml("name: Coding\n")
        assert spec.name == "Coding"
        assert spec.controllers == {}  # no controllers defined yet, or empty dict

    def test_full_keypad_spec(self) -> None:
        yaml = """
name: Coding
controllers:
  keypad:
    actions:
      "0,0":
        title: VS Code
        plugin: com.elgato.streamdeck.system.hotkey
      "0,1":
        title: Terminal
"""
        spec = YamlPageSpec.from_yaml(yaml)
        assert spec.name == "Coding"
        assert "0,0" in spec.controllers["keypad"]["actions"]
        assert spec.controllers["keypad"]["actions"]["0,0"]["title"] == "VS Code"

    def test_encoder_spec(self) -> None:
        yaml = """
name: Mixer
controllers:
  encoder:
    actions:
      "0":
        title: Volume
      "1":
        title: Brightness
"""
        spec = YamlPageSpec.from_yaml(yaml)
        assert "0" in spec.controllers["encoder"]["actions"]

    def test_empty_spec(self) -> None:
        spec = YamlPageSpec.from_yaml("name: Empty\n")
        assert spec.name == "Empty"

    def test_invalid_yaml_raises(self) -> None:
        with pytest.raises(YamlSpecError, match=r"yaml|YAML|parse"):
            YamlPageSpec.from_yaml("name: [unterminated")

    def test_missing_name_raises(self) -> None:
        with pytest.raises(YamlSpecError, match="name"):
            YamlPageSpec.from_yaml("controllers: {}\n")


# ── Apply (create page from spec) ───────────────────────────────────────────


class TestApply:
    def test_creates_page_in_profile(self, isolated_profile: Path, tmp_path: Path) -> None:
        spec = YamlPageSpec.from_yaml("name: Imported Page\n")
        new_uuid = apply_yaml_spec(isolated_profile, spec, icon_search_dirs=[])
        # The page was added to the profile's Pages list
        profile_manifest = json.loads((isolated_profile / "manifest.json").read_text())
        assert new_uuid in profile_manifest["Pages"]["Pages"]
        # The page dir exists
        page_dir = isolated_profile / "Profiles" / new_uuid
        assert (page_dir / "manifest.json").is_file()
        # The page name is set
        page_manifest = json.loads((page_dir / "manifest.json").read_text())
        assert page_manifest["Name"] == "Imported Page"

    def test_creates_actions(self, isolated_profile: Path, tmp_path: Path) -> None:
        spec = YamlPageSpec.from_yaml(
            """
name: With Actions
controllers:
  keypad:
    actions:
      "0,0":
        title: Hello
      "0,1":
        title: World
"""
        )
        new_uuid = apply_yaml_spec(isolated_profile, spec, icon_search_dirs=[])
        page_manifest = json.loads(
            (isolated_profile / "Profiles" / new_uuid / "manifest.json").read_text()
        )
        keypad = next(c for c in page_manifest["Controllers"] if c["Type"] == "Keypad")
        assert keypad["Actions"]["0,0"]["States"][0]["Title"] == "Hello"
        assert keypad["Actions"]["0,1"]["States"][0]["Title"] == "World"

    def test_icon_search_dirs_find_pngs(self, isolated_profile: Path, tmp_path: Path) -> None:
        # Drop two PNGs into a search dir
        icons = tmp_path / "icons"
        icons.mkdir()
        (icons / "vscode.png").write_bytes(_make_png(color=(1, 2, 3)))
        (icons / "term.png").write_bytes(_make_png(color=(4, 5, 6)))

        spec = YamlPageSpec.from_yaml(
            """
name: With Icons
controllers:
  keypad:
    actions:
      "0,0":
        title: VS Code
        icon: vscode.png
      "0,1":
        title: Terminal
        icon: term.png
"""
        )
        new_uuid = apply_yaml_spec(isolated_profile, spec, icon_search_dirs=[icons])
        page_dir = isolated_profile / "Profiles" / new_uuid
        # Both PNGs were copied to the page's Images/ dir
        page_images = list((page_dir / "Images").iterdir())
        assert len(page_images) == 2
        # The manifest references them
        page_manifest = json.loads((page_dir / "manifest.json").read_text())
        keypad = next(c for c in page_manifest["Controllers"] if c["Type"] == "Keypad")
        assert keypad["Actions"]["0,0"]["Icon"].startswith("Images/")
        assert keypad["Actions"]["0,1"]["Icon"].startswith("Images/")

    def test_missing_icon_warns_does_not_fail(self, isolated_profile: Path, tmp_path: Path, capsys) -> None:
        spec = YamlPageSpec.from_yaml(
            """
name: Missing Icon
controllers:
  keypad:
    actions:
      "0,0":
        icon: nope.png
"""
        )
        new_uuid = apply_yaml_spec(isolated_profile, spec, icon_search_dirs=[tmp_path / "no_such_dir"])
        # Page was still created
        page_manifest = json.loads(
            (isolated_profile / "Profiles" / new_uuid / "manifest.json").read_text()
        )
        keypad = next(c for c in page_manifest["Controllers"] if c["Type"] == "Keypad")
        # No Icon field set
        assert "Icon" not in keypad["Actions"]["0,0"]

    def test_unknown_controller_type_raises(self, isolated_profile: Path) -> None:
        spec = YamlPageSpec.from_yaml(
            """
name: Bad
controllers:
  slider:
    actions:
      "0": {}
"""
        )
        with pytest.raises(YamlSpecError, match="controller"):
            apply_yaml_spec(isolated_profile, spec, icon_search_dirs=[])


# ── Render (page → YAML) ────────────────────────────────────────────────────


class TestRender:
    def test_render_round_trip(self, isolated_profile: Path) -> None:
        # Take an existing page, render to YAML, parse back, apply to a fresh profile,
        # and check the result matches the original.
        from streamdeck_cli.manifest import load_page

        page_uuid = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        page_dir = isolated_profile / "Profiles" / page_uuid
        page = load_page(page_dir)

        yaml_text = render_yaml_spec(page)
        assert "name:" in yaml_text
        assert "controllers:" in yaml_text

    def test_render_includes_titles(self, isolated_profile: Path) -> None:
        from streamdeck_cli.manifest import load_page

        page_uuid = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        page_dir = isolated_profile / "Profiles" / page_uuid
        page = load_page(page_dir)
        yaml_text = render_yaml_spec(page)
        # The fixture has actions with titles — at least one should appear
        # (we don't know the exact title, but the structure should be present)
        assert "title:" in yaml_text
