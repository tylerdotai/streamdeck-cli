"""Tests for profile-level diff, merge, and JSON/YAML export.

A profile is a tree of on-disk artifacts. Diffing two profiles means
comparing their pages (manifests + Images/) structurally. Merging applies
a set of changes from one profile to another.

Profile export (to JSON or YAML) produces a single text file that contains
every page's manifest, with images referenced by path. Lighter than the
zip backup, friendlier to git, diff-friendly.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from streamdeck_cli.profile_io import (
    diff_profiles,
    export_profile,
    import_profile,
    merge_profiles,
)
from tests.conftest import PROFILE_DIR


@pytest.fixture
def profile_a(tmp_path: Path) -> Path:
    """A copy of the real fixture — used as the 'base'."""
    dest = tmp_path / "a.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


@pytest.fixture
def profile_b(tmp_path: Path) -> Path:
    """A second independent copy of the real fixture — used as the 'other'."""
    dest = tmp_path / "b.sdProfile"
    shutil.copytree(PROFILE_DIR, dest)
    return dest


# ── Export ──────────────────────────────────────────────────────────────────


class TestExportJson:
    def test_round_trip_json(self, profile_a: Path, tmp_path: Path) -> None:
        out = tmp_path / "profile.json"
        export_profile(profile_a, out, fmt="json")
        assert out.is_file()
        # Validate the JSON parses and has the right top-level shape
        data = json.loads(out.read_text())
        assert "name" in data
        assert "device" in data
        assert "pages" in data
        assert isinstance(data["pages"], list)
        assert len(data["pages"]) > 0
        # Each page has a manifest and a page UUID
        for page in data["pages"]:
            assert "uuid" in page
            assert "manifest" in page

    def test_round_trip_yaml(self, profile_a: Path, tmp_path: Path) -> None:
        out = tmp_path / "profile.yaml"
        export_profile(profile_a, out, fmt="yaml")
        assert out.is_file()
        data = yaml.safe_load(out.read_text())
        assert data["name"]
        assert len(data["pages"]) > 0

    def test_unknown_format_raises(self, profile_a: Path, tmp_path: Path) -> None:
        out = tmp_path / "profile.xml"
        with pytest.raises(ValueError, match="format"):
            export_profile(profile_a, out, fmt="xml")


# ── Import ──────────────────────────────────────────────────────────────────


class TestImport:
    def test_import_creates_pages(self, profile_a: Path, tmp_path: Path) -> None:
        # Export profile A, then import into an empty destination
        out = tmp_path / "profile.json"
        export_profile(profile_a, out, fmt="json")

        # Fresh dest profile
        dest = tmp_path / "dest.sdProfile"
        shutil.copytree(PROFILE_DIR, dest)
        # Strip pages from the dest first
        dest_manifest = json.loads((dest / "manifest.json").read_text())
        page_uuids = list(dest_manifest["Pages"]["Pages"])
        dest_manifest["Pages"]["Pages"] = []
        # Need a current and default; set them to the first page in profile A
        export_data = json.loads(out.read_text())
        first_page_uuid = export_data["pages"][0]["uuid"]
        dest_manifest["Pages"]["Current"] = first_page_uuid
        dest_manifest["Pages"]["Default"] = first_page_uuid
        (dest / "manifest.json").write_text(json.dumps(dest_manifest, indent=4))
        for puid in page_uuids:
            shutil.rmtree(dest / "Profiles" / puid, ignore_errors=True)

        # Import — should re-create the pages
        result = import_profile(dest, out, fmt="json")
        assert len(result.created) > 0
        # The destination now has the pages back
        for puid in page_uuids:
            assert (dest / "Profiles" / puid / "manifest.json").is_file()


# ── Diff ────────────────────────────────────────────────────────────────────


class TestDiff:
    def test_identical_profiles_have_no_diff(self, profile_a: Path, profile_b: Path) -> None:
        result = diff_profiles(profile_a, profile_b)
        assert result.is_empty()

    def test_added_page_detected(self, profile_a: Path, profile_b: Path) -> None:
        # Add a new page to profile_a. diff(a, b) shows the diff to turn a into b,
        # so a newly-added page in a is "removed" relative to b.
        from streamdeck_cli.writes import create_page

        new_uuid = create_page(profile_a, name="Added")
        result = diff_profiles(profile_a, profile_b)
        assert not result.is_empty()
        removed_uuids = [p.uuid for p in result.removed]
        assert new_uuid in removed_uuids

    def test_added_page_detected_in_target(self, profile_a: Path, profile_b: Path) -> None:
        # Add a new page to profile_a. diff(b, a) shows the diff to turn b into a,
        # so the new page in a is "added" relative to b.
        from streamdeck_cli.writes import create_page

        new_uuid = create_page(profile_a, name="Added")
        result = diff_profiles(profile_b, profile_a)
        assert not result.is_empty()
        added_uuids = [p.uuid for p in result.added]
        assert new_uuid in added_uuids

    def test_removed_page_detected(self, profile_a: Path, profile_b: Path) -> None:
        # Remove a page from profile_b that exists in profile_a
        from streamdeck_cli.writes import delete_page

        # Pick a non-current, non-default page from profile_b
        b_manifest = json.loads((profile_b / "manifest.json").read_text())
        pages = b_manifest["Pages"]["Pages"]
        current = b_manifest["Pages"]["Current"]
        default = b_manifest["Pages"]["Default"]
        target = next(p for p in pages if p != current and p != default)
        delete_page(profile_b, target)

        result = diff_profiles(profile_a, profile_b)
        assert not result.is_empty()
        removed_uuids = [p.uuid for p in result.removed]
        assert target in removed_uuids

    def test_modified_page_detected(self, profile_a: Path, profile_b: Path) -> None:
        # Change a page's name in profile_a
        a_manifest = json.loads((profile_a / "manifest.json").read_text())
        target_page = a_manifest["Pages"]["Pages"][0]
        page_path = profile_a / "Profiles" / target_page / "manifest.json"
        page_data = json.loads(page_path.read_text())
        page_data["Name"] = "Modified Name"
        page_path.write_text(json.dumps(page_data, indent=4))

        result = diff_profiles(profile_a, profile_b)
        assert not result.is_empty()
        modified_uuids = [p.uuid for p in result.modified]
        assert target_page in modified_uuids


# ── Merge ───────────────────────────────────────────────────────────────────


class TestMerge:
    def test_merge_added_page_into_target(self, profile_a: Path, profile_b: Path, tmp_path: Path) -> None:
        # Add a new page to profile_a, then merge that change into profile_b.
        # diff(b, a) shows what needs to change to turn b into a (i.e. the
        # new page needs to be "added" to b).
        from streamdeck_cli.writes import create_page

        new_uuid = create_page(profile_a, name="To Be Merged")
        diff = diff_profiles(profile_b, profile_a)
        result = merge_profiles(profile_b, diff)
        assert result.applied == 1

        b_manifest = json.loads((profile_b / "manifest.json").read_text())
        assert new_uuid in b_manifest["Pages"]["Pages"]
        assert (profile_b / "Profiles" / new_uuid / "manifest.json").is_file()

    def test_merge_refuses_to_overwrite_existing(self, profile_a: Path, profile_b: Path) -> None:
        # Modify a shared page in profile_a, then try to merge
        a_manifest = json.loads((profile_a / "manifest.json").read_text())
        target_page = a_manifest["Pages"]["Pages"][0]
        page_path = profile_a / "Profiles" / target_page / "manifest.json"
        page_data = json.loads(page_path.read_text())
        page_data["Name"] = "Different Name"
        page_path.write_text(json.dumps(page_data, indent=4))

        # diff(b, a) shows the modification
        diff = diff_profiles(profile_b, profile_a)
        result = merge_profiles(profile_b, diff, overwrite=False)
        # The page wasn't replaced
        b_manifest = json.loads((profile_b / "Profiles" / target_page / "manifest.json").read_text())
        assert b_manifest["Name"] != "Different Name"
        assert result.skipped >= 1

    def test_merge_with_overwrite_replaces(self, profile_a: Path, profile_b: Path) -> None:
        a_manifest = json.loads((profile_a / "manifest.json").read_text())
        target_page = a_manifest["Pages"]["Pages"][0]
        page_path = profile_a / "Profiles" / target_page / "manifest.json"
        page_data = json.loads(page_path.read_text())
        page_data["Name"] = "Different Name"
        page_path.write_text(json.dumps(page_data, indent=4))

        diff = diff_profiles(profile_b, profile_a)
        merge_profiles(profile_b, diff, overwrite=True)
        b_manifest = json.loads((profile_b / "Profiles" / target_page / "manifest.json").read_text())
        assert b_manifest["Name"] == "Different Name"

    def test_merge_handles_removed_pages(self, profile_a: Path, profile_b: Path, tmp_path: Path) -> None:
        # Remove a non-current, non-default page from profile_b
        from streamdeck_cli.writes import delete_page

        b_manifest = json.loads((profile_b / "manifest.json").read_text())
        pages = b_manifest["Pages"]["Pages"]
        current = b_manifest["Pages"]["Current"]
        default = b_manifest["Pages"]["Default"]
        target = next(p for p in pages if p != current and p != default)
        delete_page(profile_b, target)

        # diff(a, b) — a has the target, b doesn't, so target is "removed" from a's perspective
        diff = diff_profiles(profile_a, profile_b)
        # We want to merge the "removed" delta into profile_a
        merge_profiles(profile_a, diff, allow_remove=True)
        a_manifest = json.loads((profile_a / "manifest.json").read_text())
        assert target not in a_manifest["Pages"]["Pages"]
