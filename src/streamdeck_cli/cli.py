"""Click-based CLI for the streamdeck-cli tool.

Commands map 1:1 to the public API in the other modules — they're thin shells
that parse args, call into the library, and render output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from streamdeck_cli import __version__
from streamdeck_cli.icons import IconError, set_icon
from streamdeck_cli.listing import list_devices, list_pages, list_profiles
from streamdeck_cli.paths import resolve_profile_root
from streamdeck_cli.profile_io import (
    ProfileIOError,
    diff_profiles,
    export_profile,
    import_profile,
    merge_profiles,
)
from streamdeck_cli.validate import _page_dir_exists, validate_profile
from streamdeck_cli.writes import (
    backup_profile,
    clone_page,
    create_page,
    delete_page,
    rename_page,
    restore_profile,
    set_current_page,
)
from streamdeck_cli.yaml_pages import YamlPageSpec, YamlSpecError, apply_yaml_spec, render_yaml_spec

# ── Shared options ──────────────────────────────────────────────────────────


def _resolve_root(install_root: Path | None, profile_dir: Path | None) -> Path:
    """Pick the install root from --install-root or the system default."""
    if install_root is not None:
        return resolve_profile_root(install_root).root
    if profile_dir is not None:
        # Caller is operating on a specific profile; return the install root.
        return resolve_profile_root(profile_dir.parent).root
    return resolve_profile_root().root


def _resolve_page_dir(profile_dir: Path, page_uuid: str) -> Path:
    """Return the on-disk page dir matching ``page_uuid`` (case-insensitive)."""
    pages_dir = profile_dir / "Profiles"
    if not _page_dir_exists(pages_dir, page_uuid):
        raise click.ClickException(f"page {page_uuid} not found in {profile_dir}")
    return next(p for p in pages_dir.iterdir() if p.is_dir() and p.name.lower() == page_uuid.lower())


def _resolve_profile_dir(install_root: Path | None, profile_dir: Path | None) -> Path:
    """Return the .sdProfile directory to operate on."""
    if profile_dir is not None:
        return profile_dir
    root = _resolve_root(install_root, None)
    profiles = list_profiles(root)
    if not profiles:
        raise click.ClickException(f"no profiles found under {root}")
    return profiles[0].path


# ── Top-level ───────────────────────────────────────────────────────────────


@click.group()
@click.version_option(__version__, prog_name="streamdeck")
def main() -> None:
    """Manage Elgato Stream Deck profiles, pages, and actions from the terminal."""


@main.command("list-devices")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_list_devices(install_root: Path | None) -> None:
    """List connected Stream Deck devices."""
    root = _resolve_root(install_root, None)
    for device in list_devices(root):
        click.echo(f"{device.model}\t{device.device_class()}\t{device.uuid}")


@main.command("list-profiles")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_list_profiles(install_root: Path | None) -> None:
    """List all profiles."""
    root = _resolve_root(install_root, None)
    for profile in list_profiles(root):
        click.echo(f"{profile.name}\t{profile.device.model}\t{profile.path}")


@main.command("list-pages")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_list_pages(install_root: Path | None, profile_dir: Path | None) -> None:
    """List active pages for a profile (defaults to the only profile)."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    for p in list_pages(pd):
        flags = []
        if p.is_current:
            flags.append("current")
        if p.is_default:
            flags.append("default")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        click.echo(f"{p.uuid}\t{p.name or '(unnamed)'}{flag_str}")


@main.command("show-page")
@click.argument("uuid")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_show_page(uuid: str, install_root: Path | None, profile_dir: Path | None) -> None:
    """Print the JSON manifest of a page."""
    from streamdeck_cli.validate import _page_dir_exists
    pd = _resolve_profile_dir(install_root, profile_dir)
    pages_dir = pd / "Profiles"
    if not _page_dir_exists(pages_dir, uuid):
        raise click.ClickException(f"page {uuid} not found")
    # Find the actual (case-correct) dir name
    actual = _resolve_page_dir(pd, uuid)
    click.echo((actual / "manifest.json").read_text())


@main.command("new-page")
@click.option("--name", required=False, default=None, help="Name for the new page (ignored if --from-yaml is set)")
@click.option("--icon", default="", help="Icon path (relative to page Images/)")
@click.option("--from-yaml", "from_yaml", default=None, type=click.Path(exists=True, path_type=Path),
              help="Create the page from a YAML spec file")
@click.option("--to-page", "target_uuid", default=None,
              help="Update an existing page by UUID instead of creating a new one (requires --from-yaml)")
@click.option("--icons-dir", "icons_dirs", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Directory to search for icons referenced in the YAML spec (repeatable)")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_new_page(
    name: str | None,
    icon: str,
    from_yaml: Path | None,
    target_uuid: str | None,
    icons_dirs: tuple[Path, ...],
    install_root: Path | None,
    profile_dir: Path | None,
) -> None:
    """Create a new empty page, or populate one from a YAML spec.

    With --to-page, update an existing page by UUID from a YAML spec instead
    of creating a new one. The page's UUID is preserved.
    """
    if target_uuid is not None and from_yaml is None:
        raise click.ClickException("--to-page requires --from-yaml")
    if from_yaml is None and not name:
        raise click.ClickException("--name is required unless --from-yaml is set")
    pd = _resolve_profile_dir(install_root, profile_dir)
    if from_yaml is not None:
        text = from_yaml.read_text()
        try:
            spec = YamlPageSpec.from_yaml(text)
        except YamlSpecError as e:
            raise click.ClickException(str(e)) from None
        try:
            new_uuid = apply_yaml_spec(
                pd, spec,
                icon_search_dirs=list(icons_dirs),
                target_uuid=target_uuid,
            )
        except (YamlSpecError, FileNotFoundError) as e:
            raise click.ClickException(str(e)) from None
        click.echo(new_uuid)
    else:
        new_uuid = create_page(pd, name=name or "", icon=icon)
        click.echo(new_uuid)


@main.command("show-spec")
@click.argument("page_uuid")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Write YAML to this file instead of stdout")
def cmd_show_spec(
    page_uuid: str, install_root: Path | None, profile_dir: Path | None, output: Path | None
) -> None:
    """Render a page's manifest as a YAML spec."""
    from streamdeck_cli.manifest import load_page

    pd = _resolve_profile_dir(install_root, profile_dir)
    page_dir = _resolve_page_dir(pd, page_uuid)
    page = load_page(page_dir)
    yaml_text = render_yaml_spec(page)
    if output is not None:
        output.write_text(yaml_text)
        click.echo(f"wrote {output}")
    else:
        click.echo(yaml_text, nl=False)


@main.command("clone-page")
@click.argument("source_uuid")
@click.option("--name", default=None, help="Name for the cloned page")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_clone_page(
    source_uuid: str,
    name: str | None,
    install_root: Path | None,
    profile_dir: Path | None,
) -> None:
    """Clone a page (manifest + images) to a new UUID."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    new_uuid = clone_page(pd, source_uuid, new_name=name)
    click.echo(new_uuid)


@main.command("delete-page")
@click.argument("uuid")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.confirmation_option(prompt="Delete this page?")
def cmd_delete_page(uuid: str, install_root: Path | None, profile_dir: Path | None) -> None:
    """Delete a page by UUID (refuses current/default)."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    delete_page(pd, uuid)
    click.echo(f"deleted {uuid}")


@main.command("rename-page")
@click.argument("uuid")
@click.argument("new_name")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_rename_page(
    uuid: str, new_name: str, install_root: Path | None, profile_dir: Path | None
) -> None:
    """Rename a page by UUID. Does not change its position in the rotation."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    rename_page(pd, uuid, new_name=new_name)
    click.echo(f"renamed {uuid} → {new_name!r}")


@main.command("set-icon")
@click.argument("page_uuid")
@click.argument("key")
@click.argument("png_path", type=click.Path(exists=True, path_type=Path))
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_set_icon(
    page_uuid: str,
    key: str,
    png_path: Path,
    install_root: Path | None,
    profile_dir: Path | None,
) -> None:
    """Assign a PNG icon to a key on a page.

    PAGE_UUID selects the page (from `list-pages`).

    KEY selects the action: 'col,row' for keypad (e.g. '0,0') or 'row' for
    encoder (e.g. '0').

    PNG_PATH is the source icon. It's copied into the page's Images/ dir
    under a content-hashed filename.
    """
    pd = _resolve_profile_dir(install_root, profile_dir)
    page_dir = _resolve_page_dir(pd, page_uuid)
    try:
        rel = set_icon(page_dir, key, png_path)
    except IconError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"set icon on {page_uuid} key {key} -> {rel}")


@main.command("remove-icon")
@click.argument("page_uuid")
@click.argument("key")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_remove_icon(
    page_uuid: str,
    key: str,
    install_root: Path | None,
    profile_dir: Path | None,
) -> None:
    """Remove the icon reference from a key (PNG file is kept on disk)."""
    from streamdeck_cli.icons import remove_icon

    pd = _resolve_profile_dir(install_root, profile_dir)
    page_dir = _resolve_page_dir(pd, page_uuid)
    try:
        removed = remove_icon(page_dir, key)
    except IconError as e:
        raise click.ClickException(str(e)) from None
    if not removed:
        raise click.ClickException(f"no icon to remove at key {key}")
    click.echo(f"removed icon from {page_uuid} key {key}")


@main.command("set-current")
@click.argument("uuid")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_set_current(uuid: str, install_root: Path | None, profile_dir: Path | None) -> None:
    """Set the current page."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    set_current_page(pd, uuid)
    click.echo(f"current page is now {uuid}")


@main.command("validate")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_validate(install_root: Path | None, profile_dir: Path | None) -> None:
    """Validate manifests under the install root or a specific profile."""
    target: Path
    if profile_dir is not None:
        target = profile_dir
    elif install_root is not None:
        target = install_root
    else:
        target = resolve_profile_root().root

    result = validate_profile(target)
    for e in result.errors:
        click.echo(f"ERROR: {e}", err=True)
    for w in result.warnings:
        click.echo(f"WARN: {w}")
    if not result.ok:
        sys.exit(1)


@main.command("backup")
@click.option("-o", "--output", "output", required=True, type=click.Path(path_type=Path))
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_backup(
    output: Path, install_root: Path | None, profile_dir: Path | None
) -> None:
    """Back up a profile to a zip file."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    out = backup_profile(pd, dest=output)
    click.echo(f"wrote {out}")


@main.command("restore")
@click.argument("backup", type=click.Path(exists=True, path_type=Path))
@click.option("--install-root", type=click.Path(path_type=Path), default=None)
def cmd_restore(backup: Path, install_root: Path | None) -> None:
    """Restore a profile from a zip backup."""
    root = install_root if install_root is not None else resolve_profile_root().root
    restore_profile(backup, root)
    click.echo(f"restored {backup} into {root}")


@main.command("export")
@click.option("-o", "--output", "output", required=True, type=click.Path(path_type=Path),
              help="Output file (.json or .yaml)")
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", type=click.Path(exists=True, path_type=Path), default=None)
def cmd_export(output: Path, install_root: Path | None, profile_dir: Path | None) -> None:
    """Export a profile to JSON or YAML (lighter than the zip backup)."""
    pd = _resolve_profile_dir(install_root, profile_dir)
    fmt: str
    if output.suffix.lower() in (".yaml", ".yml"):
        fmt = "yaml"
    elif output.suffix.lower() == ".json":
        fmt = "json"
    else:
        raise click.ClickException(f"output must end in .json, .yaml, or .yml (got {output.suffix!r})")
    try:
        export_profile(pd, output, fmt=fmt)  # type: ignore[arg-type]
    except ProfileIOError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"wrote {output} ({fmt})")


@main.command("import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--install-root", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--profile-dir", "profile_dir", required=True, type=click.Path(exists=True, path_type=Path))
def cmd_import(source: Path, install_root: Path | None, profile_dir: Path) -> None:
    """Import a JSON or YAML profile export into a profile dir."""
    try:
        result = import_profile(profile_dir, source)
    except ProfileIOError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"created {len(result.created)} page(s), updated {len(result.updated)} page(s)")
    for err in result.errors:
        click.echo(f"ERROR: {err}", err=True)


@main.command("diff")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.argument("target", type=click.Path(exists=True, path_type=Path))
def cmd_diff(source: Path, target: Path) -> None:
    """Show the diff to turn SOURCE into TARGET (added/removed/modified pages)."""
    d = diff_profiles(source, target)
    if d.is_empty():
        click.echo("no differences")
        return
    for p in d.added:
        click.echo(f"+ {p.uuid}\t{p.name}")
    for p in d.removed:
        click.echo(f"- {p.uuid}\t{p.name}")
    for p in d.modified:
        click.echo(f"~ {p.uuid}\t{p.name}")


@main.command("merge")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option("--overwrite/--no-overwrite", default=False,
              help="Overwrite modified pages in the target (default: skip them)")
@click.option("--allow-remove/--no-allow-remove", default=False,
              help="Allow removing pages from the target (default: skip them)")
def cmd_merge(source: Path, target: Path, overwrite: bool, allow_remove: bool) -> None:
    """Apply changes from SOURCE into TARGET.

    The diff is computed as: 'what would I need to change in TARGET to make it
    match SOURCE?'. Added pages from SOURCE are created in TARGET. Modified
    pages in TARGET are only overwritten if --overwrite is set. Pages missing
    from SOURCE are only removed from TARGET if --allow-remove is set.
    """
    d = diff_profiles(target, source)
    result = merge_profiles(target, d, overwrite=overwrite, allow_remove=allow_remove)
    click.echo(f"applied {result.applied} change(s), skipped {result.skipped}")
    for err in result.errors:
        click.echo(f"ERROR: {err}", err=True)


if __name__ == "__main__":
    main()
