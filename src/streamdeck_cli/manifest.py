"""Dataclasses + loaders/dumpers for the reverse-engineered Stream Deck manifest schema.

Tested against Stream Deck 7.3.1 (build 22604) on macOS.

Schema reference (see ``docs/schema.md`` for the full version):

- ``Profile`` lives at ``<root>/ProfilesV3/<profile-uuid>.sdProfile/manifest.json``
  and references a list of page UUIDs.
- Each ``Page`` lives at ``<profile>/Profiles/<page-uuid>/manifest.json`` and
  contains two controllers (Keypad and Encoder) keyed by grid coordinates like
  ``"0,0"`` → ``"7,4"`` for an XL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Device:
    """Identifies a single physical Stream Deck plugged in."""

    model: str
    uuid: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        return cls(model=str(data["Model"]), uuid=str(data["UUID"]))

    def to_dict(self) -> dict[str, Any]:
        return {"Model": self.model, "UUID": self.uuid}

    def device_class(self) -> str:
        """Best-effort human-friendly name for the model number."""
        known = {
            "20GBD9901": "Stream Deck XL (Gen 1)",
            "20GAT9901": "Stream Deck Plus",
            "20GAI9901": "Stream Deck (Gen 1, 15-key)",
            "20GAS9901": "Stream Deck Studio",
            "20GAK9901": "Stream Deck Pedal",
            "20GAL9901": "Stream Deck Neo",
        }
        return known.get(self.model, f"Unknown Stream Deck model {self.model}")


@dataclass(frozen=True)
class PagesBlock:
    """The ``Pages`` block of a profile manifest."""

    current: str
    default: str
    active: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PagesBlock:
        return cls(
            current=str(data["Current"]),
            default=str(data["Default"]),
            active=tuple(str(p) for p in data["Pages"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"Current": self.current, "Default": self.default, "Pages": list(self.active)}


@dataclass(frozen=True)
class Profile:
    """A single ``.sdProfile`` directory."""

    name: str
    version: str
    device: Device
    pages: PagesBlock
    path: Path

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path) -> Profile:
        return cls(
            name=str(data["Name"]),
            version=str(data["Version"]),
            device=Device.from_dict(data["Device"]),
            pages=PagesBlock.from_dict(data["Pages"]),
            path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "Name": self.name,
            "Version": self.version,
            "Device": self.device.to_dict(),
            "Pages": self.pages.to_dict(),
        }


@dataclass(frozen=True)
class PageController:
    """A single controller (Keypad or Encoder) within a page."""

    type: str  # "Keypad" or "Encoder"
    actions: dict[str, Any] | None  # keyed by "col,row" string for Keypads

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageController:
        return cls(
            type=str(data["Type"]),
            actions=data.get("Actions") if data.get("Actions") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"Type": self.type, "Actions": self.actions}


@dataclass(frozen=True)
class Page:
    """A single page within a profile."""

    name: str
    icon: str
    controllers: list[PageController]
    path: Path

    @property
    def uuid(self) -> str:
        return self.path.name

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path) -> Page:
        return cls(
            name=str(data.get("Name", "")),
            icon=str(data.get("Icon", "")),
            controllers=[PageController.from_dict(c) for c in data.get("Controllers", [])],
            path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "Name": self.name,
            "Icon": self.icon,
            "Controllers": [c.to_dict() for c in self.controllers],
        }


# ── File loaders ────────────────────────────────────────────────────────────


def load_page(page_dir: Path) -> Page:
    """Read a page manifest from disk."""
    manifest_path = page_dir / "manifest.json"
    with manifest_path.open() as fh:
        return Page.from_dict(json.load(fh), path=page_dir)


def load_profile(profile_dir: Path) -> Profile:
    """Read a profile manifest from disk."""
    manifest_path = profile_dir / "manifest.json"
    with manifest_path.open() as fh:
        return Profile.from_dict(json.load(fh), path=profile_dir)


def load_profile_from_root(root: Path) -> Profile:
    """Find the first ``.sdProfile`` under ``root`` and load it."""
    profiles_v3 = root / "ProfilesV3"
    for entry in profiles_v3.iterdir():
        if entry.is_dir() and entry.suffix == ".sdProfile":
            return load_profile(entry)
    raise FileNotFoundError(f"no .sdProfile directory found under {profiles_v3}")


def find_profile_dirs(root: Path) -> list[Path]:
    """Return all ``.sdProfile`` directories under ``root/ProfilesV3``."""
    profiles_v3 = root / "ProfilesV3"
    if not profiles_v3.exists():
        return []
    return [p for p in sorted(profiles_v3.iterdir()) if p.is_dir() and p.suffix == ".sdProfile"]
