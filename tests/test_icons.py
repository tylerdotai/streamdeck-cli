"""Tests for the `set-icon` operation — write a PNG to a (page, key) coord.

The icon is stored in the page's ``Images/`` directory and referenced from
the action manifest at the given key coordinate.
"""
from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

import pytest

from streamdeck_cli.icons import IconError, set_icon
from tests.conftest import PROFILE_DIR

# ── Minimal valid PNG generator (no Pillow dep) ────────────────────────────


def _make_png(width: int = 1, height: int = 1, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Generate a minimal valid PNG of a solid color. Useful for tests."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b""
    for _ in range(height):
        raw += b"\x00"  # filter type
        raw += bytes(color) * width
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


class TestSetIcon:
    def test_writes_png_to_images_dir(self, isolated_profile: Path, tmp_path: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png(color=(0, 255, 0)))
        set_icon(page_dir, "0,0", icon_path)
        # An image should exist under the page's Images/ dir
        images = list((page_dir / "Images").iterdir())
        assert len(images) == 1
        assert images[0].suffix == ".png"

    def test_references_image_in_action(self, isolated_profile: Path, tmp_path: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png())
        set_icon(page_dir, "0,0", icon_path)
        manifest = json.loads((page_dir / "manifest.json").read_text())
        keypad = next(c for c in manifest["Controllers"] if c["Type"] == "Keypad")
        # The action at "0,0" should now reference the image
        action = keypad["Actions"]["0,0"]
        assert "Icon" in action or "Encoder" in action
        # The Icon path should be Images/<name>.png
        icon_ref = (action.get("Icon") or action.get("Encoder", {}).get("Icon", ""))
        assert icon_ref.startswith("Images/")
        assert icon_ref.endswith(".png")

    def test_keypad_and_encoder_keys_both_supported(
        self, isolated_profile: Path, tmp_path: Path
    ) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        # Set an icon on a keypad key (col,row)
        kp_icon = tmp_path / "kp.png"
        kp_icon.write_bytes(_make_png(color=(1, 2, 3)))
        set_icon(page_dir, "0,0", kp_icon)
        # Set an icon on an encoder (just "row")
        enc_icon = tmp_path / "enc.png"
        enc_icon.write_bytes(_make_png(color=(4, 5, 6)))
        set_icon(page_dir, "0", enc_icon)  # encoder uses "0,row" but accepting "row" is friendly

    def test_creates_action_if_missing(self, isolated_profile: Path, tmp_path: Path) -> None:
        # Pick a page that's currently empty so the key has no action
        page_dir = isolated_profile / "Profiles" / "E3B4A4C1-F629-88D7-DCE5-CE8C672C96FB"
        # No "Profiles" subdir or empty page
        if not (page_dir / "Images").exists():
            (page_dir / "Images").mkdir()
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png())
        set_icon(page_dir, "0,0", icon_path)
        manifest = json.loads((page_dir / "manifest.json").read_text())
        keypad = next(c for c in manifest["Controllers"] if c["Type"] == "Keypad")
        assert keypad["Actions"] is not None
        assert "0,0" in keypad["Actions"]

    def test_rejects_non_png(self, isolated_profile: Path, tmp_path: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        bad = tmp_path / "icon.jpg"
        bad.write_bytes(b"\xff\xd8\xff")  # JPEG magic, not PNG
        with pytest.raises(IconError, match="not a PNG"):
            set_icon(page_dir, "0,0", bad)

    def test_invalid_key_format_raises(self, isolated_profile: Path, tmp_path: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png())
        with pytest.raises(IconError, match="key format"):
            set_icon(page_dir, "abc", icon_path)

    def test_missing_page_dir_raises(self, tmp_path: Path) -> None:
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png())
        with pytest.raises(IconError, match="page not found"):
            set_icon(tmp_path / "nope", "0,0", icon_path)

    def test_deterministic_filename(self, isolated_profile: Path, tmp_path: Path) -> None:
        page_dir = isolated_profile / "Profiles" / "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
        icon_path = tmp_path / "icon.png"
        icon_path.write_bytes(_make_png())
        set_icon(page_dir, "0,0", icon_path)
        # Re-set with the same content → same filename (deterministic)
        icon_path.write_bytes(_make_png())
        set_icon(page_dir, "0,0", icon_path)
        images = list((page_dir / "Images").iterdir())
        assert len(images) == 1
