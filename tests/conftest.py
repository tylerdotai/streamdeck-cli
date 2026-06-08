"""Pytest configuration: exposes the sanitized real-profile fixture path."""
from __future__ import annotations

from pathlib import Path

# Sanitized real profile fixture, committed to the repo (UUIDs + structure only,
# no images or device-identifying info).
REAL_PROFILE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "real-profile"
PROFILE_DIR = next((REAL_PROFILE_ROOT / "ProfilesV3").iterdir())

# Backwards-compat aliases
SYNTH = REAL_PROFILE_ROOT
SYNTH_ROOT = REAL_PROFILE_ROOT
