"""MCP server wrapper for streamdeck-cli.

Exposes every public CLI command as an MCP tool, so an MCP client (Claude
Code, Cursor, etc.) can manage Stream Deck profiles, pages, icons, exports,
diffs, and merges through conversation.

Run via the script entry point:

    streamdeck-mcp

Or programmatically:

    from streamdeck_cli.mcp_server import build_server, main
    server = build_server()
    server.run()  # stdio transport by default
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from streamdeck_cli.icons import IconError
from streamdeck_cli.icons import remove_icon as _remove_icon_lib
from streamdeck_cli.icons import set_icon as _set_icon_lib
from streamdeck_cli.listing import list_devices as _list_devices_lib
from streamdeck_cli.listing import list_pages as _list_pages_lib
from streamdeck_cli.listing import list_profiles as _list_profiles_lib
from streamdeck_cli.manifest import load_page
from streamdeck_cli.paths import resolve_profile_root
from streamdeck_cli.profile_io import (
    ProfileIOError,
    diff_profiles,
    export_profile,
    merge_profiles,
)
from streamdeck_cli.profile_io import (
    import_profile as _import_profile_lib,
)
from streamdeck_cli.validate import _page_dir_exists, validate_profile
from streamdeck_cli.writes import (
    backup_profile,
    create_page,
    restore_profile,
    set_current_page,
)
from streamdeck_cli.writes import (
    clone_page as _clone_page_lib,
)
from streamdeck_cli.writes import (
    delete_page as _delete_page_lib,
)
from streamdeck_cli.yaml_pages import YamlPageSpec, apply_yaml_spec, render_yaml_spec


def _resolve_root(install_root: str | None, profile_dir: str | None) -> Path:
    if install_root:
        return resolve_profile_root(Path(install_root)).root
    if profile_dir:
        return resolve_profile_root(Path(profile_dir).parent).root
    return resolve_profile_root().root


def _resolve_profile_dir(install_root: str | None, profile_dir: str | None) -> Path:
    if profile_dir:
        return Path(profile_dir)
    root = _resolve_root(install_root, None)
    profiles = _list_profiles_lib(root)
    if not profiles:
        raise ValueError(f"no profiles found under {root}")
    return profiles[0].path


def _resolve_page_dir(profile_dir: Path, page_uuid: str) -> Path:
    pages_dir = profile_dir / "Profiles"
    if not _page_dir_exists(pages_dir, page_uuid):
        raise ValueError(f"page {page_uuid} not found in {profile_dir}")
    return next(p for p in pages_dir.iterdir() if p.is_dir() and p.name.lower() == page_uuid.lower())


def build_server() -> FastMCP:
    """Build a FastMCP server with every public CLI action registered."""
    mcp = FastMCP("streamdeck")

    # ── Discovery ────────────────────────────────────────────────────────────

    @mcp.tool()
    def list_devices(install_root: str | None = None) -> list[dict[str, str]]:
        """List connected Stream Deck devices."""
        root = _resolve_root(install_root, None)
        return [
            {"model": d.model, "uuid": d.uuid, "class": d.device_class()}
            for d in _list_devices_lib(root)
        ]

    @mcp.tool()
    def list_profiles(install_root: str | None = None) -> list[dict[str, str]]:
        """List all profiles on disk."""
        root = _resolve_root(install_root, None)
        return [
            {"name": p.name, "device": p.device.model, "path": str(p.path)}
            for p in _list_profiles_lib(root)
        ]

    @mcp.tool()
    def list_pages(
        install_root: str | None = None, profile_dir: str | None = None
    ) -> list[dict[str, Any]]:
        """List active pages for a profile (defaults to the only profile)."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        return [
            {
                "uuid": p.uuid,
                "name": p.name,
                "is_current": p.is_current,
                "is_default": p.is_default,
            }
            for p in _list_pages_lib(pd)
        ]

    @mcp.tool()
    def show_page(
        page_uuid: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> dict[str, Any]:
        """Read a page's manifest and return it as a dict."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        page_dir = _resolve_page_dir(pd, page_uuid)
        raw = (page_dir / "manifest.json").read_text()
        result: dict[str, Any] = json.loads(raw)
        return result

    # ── Page write ───────────────────────────────────────────────────────────

    @mcp.tool()
    def new_page(
        name: str,
        install_root: str | None = None,
        profile_dir: str | None = None,
        icon: str = "",
        from_yaml: str | None = None,
        icons_dirs: list[str] | None = None,
    ) -> str:
        """Create a new page. If from_yaml is set, the page is populated from
        that YAML spec; icons_dirs is a list of directories to search for
        referenced icons. Returns the new page UUID.
        """
        pd = _resolve_profile_dir(install_root, profile_dir)
        if from_yaml is not None:
            text = Path(from_yaml).read_text()
            spec = YamlPageSpec.from_yaml(text)
            new_uuid = apply_yaml_spec(pd, spec, icon_search_dirs=[Path(d) for d in (icons_dirs or [])])
        else:
            new_uuid = create_page(pd, name=name, icon=icon)
        return new_uuid

    @mcp.tool()
    def clone_page(
        source_uuid: str,
        name: str | None = None,
        install_root: str | None = None,
        profile_dir: str | None = None,
    ) -> str:
        """Clone a page (manifest + images) to a new UUID. Returns the new UUID."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        new_uuid: str = _clone_page_lib(pd, source_uuid, new_name=name)
        return new_uuid

    @mcp.tool()
    def delete_page(
        page_uuid: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Delete a page by UUID. Refuses to delete current or default pages."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        _delete_page_lib(pd, page_uuid)
        return f"deleted {page_uuid}"

    @mcp.tool()
    def set_current(
        page_uuid: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Set the current page."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        set_current_page(pd, page_uuid)
        return f"current page is now {page_uuid}"

    # ── Icons ────────────────────────────────────────────────────────────────

    @mcp.tool()
    def set_icon(
        page_uuid: str,
        key: str,
        png_path: str,
        install_root: str | None = None,
        profile_dir: str | None = None,
    ) -> str:
        """Assign a PNG icon to a key on a page. Key is 'col,row' (keypad) or
        'row' (encoder). Returns the relative icon path."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        page_dir = _resolve_page_dir(pd, page_uuid)
        try:
            rel = _set_icon_lib(page_dir, key, Path(png_path))
        except IconError as e:
            raise ValueError(str(e)) from None
        return f"Images/{Path(rel).name}" if not rel.startswith("Images/") else rel

    @mcp.tool()
    def remove_icon(
        page_uuid: str, key: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Remove the icon reference from a key. The PNG file is kept on disk."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        page_dir = _resolve_page_dir(pd, page_uuid)
        removed = _remove_icon_lib(page_dir, key)
        if not removed:
            raise ValueError(f"no icon to remove at key {key}")
        return f"removed icon from {page_uuid} key {key}"

    # ── YAML spec ────────────────────────────────────────────────────────────

    @mcp.tool()
    def show_spec(
        page_uuid: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Render a page's manifest as a YAML spec string."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        page_dir = _resolve_page_dir(pd, page_uuid)
        page = load_page(page_dir)
        return render_yaml_spec(page)

    # ── Validate / backup / restore ──────────────────────────────────────────

    @mcp.tool()
    def validate(install_root: str | None = None, profile_dir: str | None = None) -> dict[str, Any]:
        """Validate manifests. Returns {"ok": bool, "errors": [...], "warnings": [...]}."""
        if profile_dir:
            target = Path(profile_dir)
        elif install_root:
            target = Path(install_root)
        else:
            target = resolve_profile_root().root
        result = validate_profile(target)
        return {"ok": result.ok, "errors": list(result.errors), "warnings": list(result.warnings)}

    @mcp.tool()
    def backup(
        output: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Back up a profile to a zip file. Returns the zip path."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        out = backup_profile(pd, dest=Path(output))
        return str(out)

    @mcp.tool()
    def restore(backup: str, install_root: str | None = None) -> str:
        """Restore a profile from a zip backup."""
        root = Path(install_root) if install_root else resolve_profile_root().root
        restore_profile(Path(backup), root)
        return f"restored {backup} into {root}"

    # ── Export / import / diff / merge ───────────────────────────────────────

    @mcp.tool()
    def export(
        output: str, install_root: str | None = None, profile_dir: str | None = None
    ) -> str:
        """Export a profile to JSON or YAML. Format is inferred from the output extension."""
        pd = _resolve_profile_dir(install_root, profile_dir)
        out = Path(output)
        fmt = "yaml" if out.suffix.lower() in (".yaml", ".yml") else "json"
        try:
            export_profile(pd, out, fmt=fmt)  # type: ignore[arg-type]
        except ProfileIOError as e:
            raise ValueError(str(e)) from None
        return f"wrote {out} ({fmt})"

    @mcp.tool()
    def import_profile(source: str, profile_dir: str) -> dict[str, list[str]]:
        """Import a JSON or YAML profile export into a profile dir."""
        try:
            result = _import_profile_lib(Path(profile_dir), Path(source))
        except ProfileIOError as e:
            raise ValueError(str(e)) from None
        return {
            "created": list(result.created),
            "updated": list(result.updated),
            "errors": list(result.errors),
        }

    @mcp.tool()
    def diff(source: str, target: str) -> dict[str, list[dict[str, str]]]:
        """Compute the diff from source to target. Returns added/removed/modified lists."""
        d = diff_profiles(Path(source), Path(target))
        return {
            "added": [{"uuid": p.uuid, "name": p.name} for p in d.added],
            "removed": [{"uuid": p.uuid, "name": p.name} for p in d.removed],
            "modified": [{"uuid": p.uuid, "name": p.name} for p in d.modified],
        }

    @mcp.tool()
    def merge(
        source: str,
        target: str,
        overwrite: bool = False,
        allow_remove: bool = False,
    ) -> dict[str, Any]:
        """Apply changes from source into target. By default only adds new pages
        (modified and removed are skipped). Pass overwrite=True to replace
        modified pages, allow_remove=True to delete missing pages."""
        d = diff_profiles(Path(target), Path(source))
        result = merge_profiles(Path(target), d, overwrite=overwrite, allow_remove=allow_remove)
        return {
            "applied": result.applied,
            "skipped": result.skipped,
            "errors": list(result.errors),
        }

    return mcp


def main() -> None:
    """Run the MCP server over stdio."""
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
