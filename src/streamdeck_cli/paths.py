"""Path resolution for the Stream Deck 7.x on-disk profile storage.

The official app writes to:

- macOS: ``~/Library/Application Support/com.elgato.StreamDeck/``
- Windows: ``%APPDATA%/Elgato/StreamDeck/``

Inside the root, profiles live under ``ProfilesV3/<uuid>.sdProfile/`` and each
profile contains a ``manifest.json`` + a ``Profiles/<page-uuid>/`` subdir per page.
"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProfileRoot:
    """Wrapper around the Stream Deck profile root directory.

    The root itself contains a single ``.sdProfile`` directory per device.
    """

    root: Path
    exists: bool

    @property
    def profiles_dir(self) -> Path:
        """The ``ProfilesV3`` directory inside the app support root."""
        return self.root / "ProfilesV3"


def default_profile_root() -> Path:
    """Return the platform-default Stream Deck profile root.

    Raises ``NotImplementedError`` on unsupported platforms.
    """
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "com.elgato.StreamDeck"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise NotImplementedError("Windows APPDATA env var is not set")
        return Path(appdata) / "Elgato" / "StreamDeck"
    raise NotImplementedError(f"streamdeck-cli does not support platform {system!r}")


def resolve_profile_root(path: Path | None = None) -> ProfileRoot:
    """Resolve a profile root from an explicit path or the platform default."""
    target = path if path is not None else default_profile_root()
    return ProfileRoot(root=target, exists=target.exists())
