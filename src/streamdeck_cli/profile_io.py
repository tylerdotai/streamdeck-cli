"""Profile-level export, import, diff, and merge.

Profiles are trees of JSON manifests plus image files. For sharing and
version control, a flat JSON or YAML representation is far friendlier
than a zip: it's diff-friendly, merge-friendly, and human-readable.

This module provides:
- export_profile: write a profile to .json or .yaml
- import_profile: read a profile export back into a destination profile dir
- diff_profiles: compute added/removed/modified pages between two profiles
- merge_profiles: apply a diff to a target profile

The format is intentionally simple:
  {
    "name": "Default Profile",
    "device": {"model": "20GBD9901", "uuid": "..."},
    "pages": [
      {
        "uuid": "<page-uuid>",
        "manifest": {... page manifest content ...},
        "images": {"<filename>": "<base64-or-bytes-blob>"}
      }
    ]
  }

Images are embedded inline (base64-encoded) for self-containment. For
larger profiles we may add a sidecar-images mode later.
"""
from __future__ import annotations

import base64
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

ExportFormat = Literal["json", "yaml"]


# ── Errors ──────────────────────────────────────────────────────────────────


class ProfileIOError(ValueError):
    """Raised for export/import/diff/merge problems."""


# ── Result dataclasses ──────────────────────────────────────────────────────


@dataclass
class PageExport:
    uuid: str
    manifest: dict[str, Any]
    images: dict[str, str]  # filename -> base64-encoded bytes


@dataclass
class ProfileExport:
    name: str
    device: dict[str, str]
    pages: list[PageExport]


@dataclass
class PageDelta:
    uuid: str
    name: str
    manifest: dict[str, Any]
    images: dict[str, bytes]  # filename -> raw bytes (decoded from b64 on load)

    @classmethod
    def from_export(cls, page: PageExport) -> PageDelta:
        return cls(
            uuid=page.uuid,
            name=page.manifest.get("Name", ""),
            manifest=page.manifest,
            images={k: base64.b64decode(v) for k, v in page.images.items()},
        )


@dataclass
class ProfileDiff:
    added: list[PageDelta] = field(default_factory=list)
    removed: list[PageDelta] = field(default_factory=list)
    modified: list[PageDelta] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified)


@dataclass
class MergeResult:
    applied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ── Export ──────────────────────────────────────────────────────────────────


def _gather_profile(profile_dir: Path) -> ProfileExport:
    """Read a profile from disk into a ProfileExport."""
    manifest_path = profile_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ProfileIOError(f"profile manifest not found: {manifest_path}")
    profile_data = json.loads(manifest_path.read_text())

    pages_dir = profile_dir / "Profiles"
    pages: list[PageExport] = []
    for puid in profile_data.get("Pages", {}).get("Pages", []):
        page_dir = pages_dir / puid
        if not page_dir.is_dir():
            continue
        page_manifest_path = page_dir / "manifest.json"
        if not page_manifest_path.is_file():
            continue
        page_manifest = json.loads(page_manifest_path.read_text())
        images: dict[str, str] = {}
        images_dir = page_dir / "Images"
        if images_dir.is_dir():
            for img in sorted(images_dir.iterdir()):
                if img.is_file() and img.suffix.lower() == ".png":
                    images[img.name] = base64.b64encode(img.read_bytes()).decode("ascii")
        pages.append(PageExport(uuid=puid, manifest=page_manifest, images=images))

    return ProfileExport(
        name=profile_data.get("Name", ""),
        device=profile_data.get("Device", {}),
        pages=pages,
    )


def _export_to_dict(export: ProfileExport) -> dict[str, Any]:
    return {
        "name": export.name,
        "device": export.device,
        "pages": [
            {"uuid": p.uuid, "manifest": p.manifest, "images": p.images}
            for p in export.pages
        ],
    }


def export_profile(profile_dir: Path, dest: Path, *, fmt: ExportFormat = "json") -> Path:
    """Write a profile to ``dest`` in the given format. Returns ``dest``."""
    export = _gather_profile(profile_dir)
    data = _export_to_dict(export)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        dest.write_text(json.dumps(data, indent=2))
    elif fmt == "yaml":
        dest.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    else:
        raise ProfileIOError(f"unknown export format: {fmt!r}; expected 'json' or 'yaml'")
    return dest


# ── Import ──────────────────────────────────────────────────────────────────


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def import_profile(
    dest_profile: Path,
    source: Path,
    *,
    fmt: ExportFormat | None = None,
) -> ImportResult:
    """Apply a profile export to ``dest_profile``.

    If ``fmt`` is None, the file extension determines the format.
    """
    if fmt is None:
        ext = source.suffix.lower()
        if ext in (".yaml", ".yml"):
            fmt = "yaml"
        elif ext == ".json":
            fmt = "json"
        else:
            raise ProfileIOError(f"can't infer format from extension: {ext}")
    raw = source.read_text()
    if fmt == "json":
        data = json.loads(raw)
    elif fmt == "yaml":
        data = yaml.safe_load(raw)
    else:
        raise ProfileIOError(f"unknown import format: {fmt!r}")

    if not isinstance(data, dict) or "pages" not in data:
        raise ProfileIOError("export file is not a valid profile export")

    result = ImportResult()
    pages_dir = dest_profile / "Profiles"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Update the dest profile's name + device if those are present
    dest_manifest_path = dest_profile / "manifest.json"
    if dest_manifest_path.is_file():
        dest_manifest = json.loads(dest_manifest_path.read_text())
    else:
        dest_manifest = {
            "Name": data.get("name", "Imported"),
            "Device": data.get("device", {}),
            "Version": "2.0",
            "Pages": {"Current": "", "Default": "", "Pages": []},
        }
    if data.get("name"):
        dest_manifest["Name"] = data["name"]
    if data.get("device"):
        dest_manifest["Device"] = data["device"]

    for page in data["pages"]:
        uuid = page["uuid"]
        manifest = page["manifest"]
        images = page.get("images") or {}

        page_dir = pages_dir / uuid
        if page_dir.is_dir():
            result.updated.append(uuid)
        else:
            page_dir.mkdir(parents=True)
            result.created.append(uuid)

        # Write manifest
        (page_dir / "manifest.json").write_text(json.dumps(manifest, indent=4))
        # Write images
        images_dir = page_dir / "Images"
        images_dir.mkdir(exist_ok=True)
        for fname, b64 in images.items():
            (images_dir / fname).write_bytes(base64.b64decode(b64))

        # Add to the dest profile's Pages list (if not present)
        if uuid not in dest_manifest["Pages"]["Pages"]:
            dest_manifest["Pages"]["Pages"].append(uuid)

    # Make sure Current and Default point at existing pages
    existing = dest_manifest["Pages"]["Pages"]
    if not dest_manifest["Pages"]["Current"] and existing:
        dest_manifest["Pages"]["Current"] = existing[0]
    if not dest_manifest["Pages"]["Default"] and existing:
        dest_manifest["Pages"]["Default"] = existing[0]

    dest_manifest_path.write_text(json.dumps(dest_manifest, indent=4))
    return result


# ── Diff ────────────────────────────────────────────────────────────────────


def _export_to_pages(export: ProfileExport) -> dict[str, PageDelta]:
    return {p.uuid: PageDelta.from_export(p) for p in export.pages}


def diff_profiles(source: Path, target: Path) -> ProfileDiff:
    """Compute the diff from ``source`` to ``target``.

    "added" = pages in target but not in source
    "removed" = pages in source but not in target
    "modified" = pages in both, but the manifest or images differ
    """
    src_export = _gather_profile(source)
    tgt_export = _gather_profile(target)
    src_pages = _export_to_pages(src_export)
    tgt_pages = _export_to_pages(tgt_export)

    diff = ProfileDiff()
    for uuid, src_page in src_pages.items():
        if uuid not in tgt_pages:
            diff.removed.append(src_page)
        elif src_page.manifest != tgt_pages[uuid].manifest or src_page.images != tgt_pages[uuid].images:
            diff.modified.append(tgt_pages[uuid])
    for uuid, tgt_page in tgt_pages.items():
        if uuid not in src_pages:
            diff.added.append(tgt_page)
    return diff


# ── Merge ───────────────────────────────────────────────────────────────────


def merge_profiles(
    target: Path,
    diff: ProfileDiff,
    *,
    overwrite: bool = False,
    allow_remove: bool = False,
) -> MergeResult:
    """Apply ``diff`` to the profile at ``target``.

    - "added" pages are created in the target
    - "modified" pages are overwritten if ``overwrite`` is True, else skipped
    - "removed" pages are deleted from the target if ``allow_remove`` is True
    """
    result = MergeResult()
    pages_dir = target / "Profiles"
    manifest_path = target / "manifest.json"
    profile_manifest = json.loads(manifest_path.read_text())
    pages_list = profile_manifest["Pages"]["Pages"]
    current = profile_manifest["Pages"].get("Current", "")
    default = profile_manifest["Pages"].get("Default", "")

    for page in diff.added:
        page_dir = pages_dir / page.uuid
        try:
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "manifest.json").write_text(json.dumps(page.manifest, indent=4))
            images_dir = page_dir / "Images"
            images_dir.mkdir(exist_ok=True)
            for fname, raw in page.images.items():
                (images_dir / fname).write_bytes(raw)
            if page.uuid not in pages_list:
                pages_list.append(page.uuid)
            result.applied += 1
        except Exception as e:  # pragma: no cover — defensive
            result.errors.append(f"add {page.uuid}: {e}")

    for page in diff.modified:
        page_dir = pages_dir / page.uuid
        if not page_dir.is_dir():
            # Treat as added
            try:
                page_dir.mkdir(parents=True, exist_ok=True)
                (page_dir / "manifest.json").write_text(json.dumps(page.manifest, indent=4))
                (page_dir / "Images").mkdir(exist_ok=True)
                if page.uuid not in pages_list:
                    pages_list.append(page.uuid)
                result.applied += 1
            except Exception as e:  # pragma: no cover
                result.errors.append(f"create-on-modify {page.uuid}: {e}")
            continue
        if not overwrite:
            result.skipped += 1
            continue
        try:
            (page_dir / "manifest.json").write_text(json.dumps(page.manifest, indent=4))
            images_dir = page_dir / "Images"
            images_dir.mkdir(exist_ok=True)
            # Write/replace images, leave others alone
            for fname, raw in page.images.items():
                (images_dir / fname).write_bytes(raw)
            result.applied += 1
        except Exception as e:  # pragma: no cover
            result.errors.append(f"modify {page.uuid}: {e}")

    for page in diff.removed:
        if not allow_remove:
            result.skipped += 1
            continue
        if page.uuid == current:
            result.errors.append(f"refusing to remove current page {page.uuid}")
            result.skipped += 1
            continue
        if page.uuid == default:
            result.errors.append(f"refusing to remove default page {page.uuid}")
            result.skipped += 1
            continue
        try:
            shutil.rmtree(pages_dir / page.uuid, ignore_errors=True)
            if page.uuid in pages_list:
                pages_list.remove(page.uuid)
            result.applied += 1
        except Exception as e:  # pragma: no cover
            result.errors.append(f"remove {page.uuid}: {e}")

    profile_manifest["Pages"]["Pages"] = pages_list
    manifest_path.write_text(json.dumps(profile_manifest, indent=4))
    return result
