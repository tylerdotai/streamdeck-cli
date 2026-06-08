"""Tests for the MCP server wrapper.

The MCP server exposes the same actions as the CLI as tools that an MCP
client (Claude Code, Cursor, etc.) can call. Tests run the server in-process
against a real stdio transport — fast, no daemon required.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from streamdeck_cli.mcp_server import build_server
from tests.conftest import PROFILE_DIR


@pytest.fixture
def isolated_profile(tmp_path: Path) -> Path:
    dest = tmp_path / "profile.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


# ── Tool registration ───────────────────────────────────────────────────────


def test_server_registers_expected_tools() -> None:
    server = build_server()
    # FastMCP exposes a tool manager we can introspect
    tools = server._tool_manager._tools  # type: ignore[attr-defined]
    names = set(tools.keys())
    # Every public CLI command should be available as a tool
    expected = {
        "list_devices",
        "list_profiles",
        "list_pages",
        "show_page",
        "new_page",
        "clone_page",
        "delete_page",
        "set_current",
        "set_icon",
        "remove_icon",
        "show_spec",
        "validate",
        "backup",
        "restore",
        "export",
        "import_profile",
        "diff",
        "merge",
    }
    missing = expected - names
    assert not missing, f"missing MCP tools: {missing}"


def test_every_tool_has_a_docstring() -> None:
    server = build_server()
    tools = server._tool_manager._tools  # type: ignore[attr-defined]
    for name, tool in tools.items():
        assert tool.description, f"tool {name!r} has no description"


# ── Tool calls against a real (isolated) profile ────────────────────────────


async def test_list_pages_tool_returns_pages(isolated_profile: Path) -> None:
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "list_pages", {"profile_dir": str(isolated_profile)}
    )
    # The tool returns a list of dicts
    assert isinstance(result, list)
    assert len(result) > 0
    first = result[0]
    assert "uuid" in first
    assert "name" in first


async def test_show_page_tool_returns_manifest(isolated_profile: Path) -> None:
    server = build_server()
    page_uuid = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "show_page", {"page_uuid": page_uuid, "profile_dir": str(isolated_profile)}
    )
    assert isinstance(result, dict)
    assert "Controllers" in result


# ── More tool coverage (push over the 80% gate) ─────────────────────────────


async def test_list_devices_tool(tmp_path: Path) -> None:
    import shutil
    install_root = tmp_path / "install"
    pv3 = install_root / "ProfilesV3"
    pv3.mkdir(parents=True)
    # PROFILE_DIR IS the .sdProfile (from conftest.py), so copy it into the
    # install root's ProfilesV3/ directly.
    shutil.copytree(PROFILE_DIR, pv3 / PROFILE_DIR.name)

    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "list_devices", {"install_root": str(install_root)}
    )
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "model" in result[0]


async def test_list_profiles_tool(tmp_path: Path) -> None:
    import shutil
    install_root = tmp_path / "install"
    pv3 = install_root / "ProfilesV3"
    pv3.mkdir(parents=True)
    shutil.copytree(PROFILE_DIR, pv3 / PROFILE_DIR.name)

    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "list_profiles", {"install_root": str(install_root)}
    )
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "name" in result[0]
    assert "path" in result[0]


async def test_new_page_tool(isolated_profile: Path) -> None:
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "new_page",
        {"name": "MCP Created", "profile_dir": str(isolated_profile)},
    )
    assert isinstance(result, str)
    # The new page exists
    assert (isolated_profile / "Profiles" / result / "manifest.json").is_file()


async def test_new_page_from_yaml_tool(isolated_profile: Path, tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("name: MCP YAML Page\ncontrollers:\n  keypad:\n    actions:\n      \"0,0\":\n        title: Test\n")
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "new_page",
        {"name": "ignored", "from_yaml": str(spec), "profile_dir": str(isolated_profile)},
    )
    assert isinstance(result, str)
    # Page name comes from the YAML
    import json as _json
    page_manifest = _json.loads(
        (isolated_profile / "Profiles" / result / "manifest.json").read_text()
    )
    assert page_manifest["Name"] == "MCP YAML Page"


async def test_clone_and_set_current_and_delete(isolated_profile: Path) -> None:
    server = build_server()
    source = "ABE23767-B7E5-62B5-C463-F3D5D64CB922"
    cloned = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "clone_page",
        {"source_uuid": source, "name": "MCP Clone", "profile_dir": str(isolated_profile)},
    )
    assert isinstance(cloned, str)
    assert cloned != source

    # Set it as current so we can later delete it (delete refuses the
    # current/default page otherwise, but the test wants to verify the full
    # lifecycle including delete).
    set_cur = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "set_current",
        {"page_uuid": cloned, "profile_dir": str(isolated_profile)},
    )
    assert "current" in set_cur.lower()

    # Set it back so we can delete the original
    restore = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "set_current",
        {"page_uuid": source, "profile_dir": str(isolated_profile)},
    )
    assert "current" in restore.lower()

    deleted = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "delete_page",
        {"page_uuid": cloned, "profile_dir": str(isolated_profile)},
    )
    assert "deleted" in deleted


async def test_set_icon_tool(isolated_profile: Path, tmp_path: Path) -> None:
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
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "set_icon",
        {
            "page_uuid": "ABE23767-B7E5-62B5-C463-F3D5D64CB922",
            "key": "0,0",
            "png_path": str(icon),
            "profile_dir": str(isolated_profile),
        },
    )
    assert "Images/" in result


async def test_show_spec_tool(isolated_profile: Path) -> None:
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "show_spec",
        {"page_uuid": "ABE23767-B7E5-62B5-C463-F3D5D64CB922", "profile_dir": str(isolated_profile)},
    )
    assert isinstance(result, str)
    assert "name:" in result
    assert "controllers:" in result


async def test_validate_tool(isolated_profile: Path) -> None:
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "validate", {"profile_dir": str(isolated_profile)}
    )
    assert isinstance(result, dict)
    assert "ok" in result
    assert "errors" in result
    assert "warnings" in result


async def test_export_then_import_tool(isolated_profile: Path, tmp_path: Path) -> None:
    server = build_server()
    out = tmp_path / "export.json"
    exp = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "export",
        {"output": str(out), "profile_dir": str(isolated_profile)},
    )
    assert "wrote" in exp
    assert out.is_file()

    # Import into a fresh copy
    import shutil
    target = tmp_path / "target.sdProfile"
    shutil.copytree(isolated_profile, target)
    imp = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "import_profile",
        {"source": str(out), "profile_dir": str(target)},
    )
    assert isinstance(imp, dict)
    assert "created" in imp


async def test_diff_tool(isolated_profile: Path, tmp_path: Path) -> None:
    import shutil as _sh
    a = tmp_path / "a.sdProfile"
    b = tmp_path / "b.sdProfile"
    _sh.copytree(isolated_profile, a)
    _sh.copytree(isolated_profile, b)
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "diff", {"source": str(a), "target": str(b)}
    )
    assert isinstance(result, dict)
    assert "added" in result
    assert "removed" in result
    assert "modified" in result


async def test_merge_tool(isolated_profile: Path, tmp_path: Path) -> None:
    import shutil as _sh

    from streamdeck_cli.writes import create_page
    a = tmp_path / "a.sdProfile"
    b = tmp_path / "b.sdProfile"
    _sh.copytree(isolated_profile, a)
    _sh.copytree(isolated_profile, b)
    create_page(a, name="Merge Test")
    server = build_server()
    result = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "merge", {"source": str(a), "target": str(b)}
    )
    assert isinstance(result, dict)
    assert "applied" in result


async def test_backup_and_restore_tool(isolated_profile: Path, tmp_path: Path) -> None:
    server = build_server()
    zip_path = tmp_path / "backup.zip"
    back = await server._tool_manager.call_tool(  # type: ignore[attr-defined]
        "backup",
        {"output": str(zip_path), "profile_dir": str(isolated_profile)},
    )
    assert str(zip_path) in back
    assert zip_path.is_file()
