"""CLI-level tests for the new export/import/diff/merge commands.

The library functions are tested in test_profile_io.py. These tests verify
the CLI surface — argument parsing, exit codes, error messages.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from streamdeck_cli.cli import main
from tests.conftest import PROFILE_DIR


@pytest.fixture
def profile_a(tmp_path: Path) -> Path:
    dest = tmp_path / "a.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


@pytest.fixture
def profile_b(tmp_path: Path) -> Path:
    dest = tmp_path / "b.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


# ── export ──────────────────────────────────────────────────────────────────


def test_export_json_happy_path(profile_a: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    runner = CliRunner()
    result = runner.invoke(main, ["export", "-o", str(out), "--profile-dir", str(profile_a)])
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "wrote" in result.output


def test_export_yaml_happy_path(profile_a: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.yaml"
    runner = CliRunner()
    result = runner.invoke(main, ["export", "-o", str(out), "--profile-dir", str(profile_a)])
    assert result.exit_code == 0, result.output
    assert out.is_file()


def test_export_rejects_bad_extension(profile_a: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.xml"
    runner = CliRunner()
    result = runner.invoke(main, ["export", "-o", str(out), "--profile-dir", str(profile_a)])
    assert result.exit_code != 0
    assert ".json" in result.output or ".yaml" in result.output


# ── import ──────────────────────────────────────────────────────────────────


def test_import_creates_pages(profile_a: Path, profile_b: Path, tmp_path: Path) -> None:
    out = tmp_path / "a.json"
    # Export A
    runner = CliRunner()
    r1 = runner.invoke(main, ["export", "-o", str(out), "--profile-dir", str(profile_a)])
    assert r1.exit_code == 0
    # Import into B (which already has the same pages — should "update")
    r2 = runner.invoke(main, ["import", str(out), "--profile-dir", str(profile_b)])
    assert r2.exit_code == 0, r2.output
    assert "created" in r2.output or "updated" in r2.output


def test_import_rejects_missing_source(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["import", str(tmp_path / "nope.json"), "--profile-dir", str(tmp_path / "x")])
    assert result.exit_code != 0


# ── diff ────────────────────────────────────────────────────────────────────


def test_diff_identical_profiles_says_no_diff(profile_a: Path, profile_b: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(profile_a), str(profile_b)])
    assert result.exit_code == 0
    assert "no differences" in result.output


def test_diff_shows_added_page(profile_a: Path, profile_b: Path) -> None:
    from streamdeck_cli.writes import create_page

    new_uuid = create_page(profile_a, name="Diff Test")
    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(profile_b), str(profile_a)])
    assert result.exit_code == 0
    assert "+" in result.output
    assert new_uuid in result.output


# ── merge ───────────────────────────────────────────────────────────────────


def test_merge_added_page(profile_a: Path, profile_b: Path) -> None:
    from streamdeck_cli.writes import create_page

    new_uuid = create_page(profile_a, name="To Merge")
    runner = CliRunner()
    result = runner.invoke(main, ["merge", str(profile_a), str(profile_b)])
    assert result.exit_code == 0, result.output
    assert "applied" in result.output
    # The new page is now in B
    b_manifest = json.loads((profile_b / "manifest.json").read_text())
    assert new_uuid in b_manifest["Pages"]["Pages"]


def test_merge_refuses_to_overwrite_by_default(profile_a: Path, profile_b: Path) -> None:
    # Modify a shared page in A
    a_manifest = json.loads((profile_a / "manifest.json").read_text())
    target = a_manifest["Pages"]["Pages"][0]
    page_path = profile_a / "Profiles" / target / "manifest.json"
    page_data = json.loads(page_path.read_text())
    page_data["Name"] = "Modified"
    page_path.write_text(json.dumps(page_data, indent=4))

    runner = CliRunner()
    result = runner.invoke(main, ["merge", str(profile_a), str(profile_b)])
    assert result.exit_code == 0
    # The page wasn't replaced
    b_manifest = json.loads((profile_b / "Profiles" / target / "manifest.json").read_text())
    assert b_manifest["Name"] != "Modified"


def test_merge_with_overwrite_replaces(profile_a: Path, profile_b: Path) -> None:
    a_manifest = json.loads((profile_a / "manifest.json").read_text())
    target = a_manifest["Pages"]["Pages"][0]
    page_path = profile_a / "Profiles" / target / "manifest.json"
    page_data = json.loads(page_path.read_text())
    page_data["Name"] = "Replaced"
    page_path.write_text(json.dumps(page_data, indent=4))

    runner = CliRunner()
    result = runner.invoke(main, ["merge", str(profile_a), str(profile_b), "--overwrite"])
    assert result.exit_code == 0
    b_manifest = json.loads((profile_b / "Profiles" / target / "manifest.json").read_text())
    assert b_manifest["Name"] == "Replaced"


# ── new-page --from-yaml CLI tests ──────────────────────────────────────────


def test_new_page_from_yaml_cli(profile_a: Path, tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("name: CLI YAML Page\ncontrollers:\n  keypad:\n    actions:\n      \"0,0\":\n        title: Hello\n")
    runner = CliRunner()
    result = runner.invoke(main, ["new-page", "--from-yaml", str(spec), "--profile-dir", str(profile_a)])
    assert result.exit_code == 0, result.output
    # A UUID was printed
    new_uuid = result.output.strip()
    assert len(new_uuid) == 36  # UUID4


def test_new_page_requires_name_or_yaml(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["new-page", "--profile-dir", str(tmp_path / "x")])
    assert result.exit_code != 0
    assert "name" in result.output.lower()


# ── show-spec CLI ───────────────────────────────────────────────────────────


def test_show_spec_cli(profile_a: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["show-spec", "ABE23767-B7E5-62B5-C463-F3D5D64CB922", "--profile-dir", str(profile_a)])
    assert result.exit_code == 0
    assert "name:" in result.output
    assert "controllers:" in result.output


def test_show_spec_to_file(profile_a: Path, tmp_path: Path) -> None:
    out = tmp_path / "spec.yaml"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "show-spec",
            "ABE23767-B7E5-62B5-C463-F3D5D64CB922",
            "--profile-dir",
            str(profile_a),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert out.is_file()


# ── remove-icon CLI ─────────────────────────────────────────────────────────


def test_remove_icon_cli(profile_a: Path, tmp_path: Path) -> None:
    import struct
    import zlib

    def _make_png() -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        raw = b"\x00\xff\x00\x00"
        idat = zlib.compress(raw)
        return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    icon = tmp_path / "icon.png"
    icon.write_bytes(_make_png())
    runner = CliRunner()
    page_uuid = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
    # Set first
    r1 = runner.invoke(
        main,
        ["set-icon", page_uuid, "0,0", str(icon), "--profile-dir", str(profile_a)],
    )
    assert r1.exit_code == 0, r1.output
    # Then remove
    r2 = runner.invoke(
        main,
        ["remove-icon", page_uuid, "0,0", "--profile-dir", str(profile_a)],
    )
    assert r2.exit_code == 0, r2.output
    assert "removed" in r2.output
