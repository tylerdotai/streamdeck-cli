# streamdeck-cli

> A command-line tool for managing **Elgato Stream Deck** profiles, pages, and actions from your terminal.

The official Elgato CLI/SDK only supports *building plugins*. There is no first-party tool for managing the profiles, pages, and actions you've already laid out in the Stream Deck app. `streamdeck-cli` **reverse-engineers the on-disk JSON schema** used by the Stream Deck 7.x desktop app and exposes it as a safe, testable Python CLI.

> **Status:** alpha. Tested against Stream Deck 7.3.1 (build 22604) on macOS. Windows path supported but untested on a real install.

## Why

If you've ever:

- Wanted to **script page rotations** for streaming / focus modes
- Wished you could **clone a page** to hand to a friend
- Needed to **back up a profile** before a risky edit
- Wished the Elgato app had a CLI for **batch page creation**

…this is the tool. It's small, dependency-free at runtime, and round-trips your existing profiles without a single character of byte-level change.

## Install

```bash
pip install streamdeck-cli
```

Or from source (recommended for development):

```bash
git clone https://github.com/tylerdotai/streamdeck-cli
cd streamdeck-cli
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```bash
# Discovery
streamdeck list-devices
streamdeck list-profiles
streamdeck list-pages

# Read
streamdeck show-page <uuid>

# Write
streamdeck new-page --name "Coding"
streamdeck clone-page <source-uuid> --name "Coding Copy"
streamdeck delete-page <uuid>            # confirmation prompt
streamdeck set-current <uuid>

# Validate
streamdeck validate

# Back up / restore
streamdeck backup -o ~/Desktop/profile.zip
streamdeck restore ~/Desktop/profile.zip
```

By default, `streamdeck-cli` reads/writes the standard install root for your
platform. Override with `--install-root` for a custom location or a backup
you're poking at.

```bash
streamdeck list-pages --install-root /Volumes/Backup/StreamDeck
```

## How it works

See [`docs/schema.md`](docs/schema.md) for the full reverse-engineered schema
reference (tested against Stream Deck 7.3.1).

**TL;DR:**

- The Stream Deck app stores everything as JSON in
  `~/Library/Application Support/com.elgato.StreamDeck/ProfilesV3/...`.
- A **profile** is `<profile-uuid>.sdProfile/manifest.json` plus a `Profiles/`
  directory of **page** UUIDs.
- A **page** is `<page-uuid>/manifest.json` with two `Controllers` (Keypad
  and Encoder) keyed by `"col,row"`.
- `streamdeck-cli` reads/writes these manifests directly, with
  atomic-write semantics and a zip-based backup format.

## Safety

- `streamdeck-cli` **never deletes the current or default page** — switch
  current first.
- All write operations are atomic (write to temp file, then rename) so a
  crash mid-edit can't corrupt your profile.
- The Stream Deck app itself takes a backup snapshot to `BackupV3/` on every
  change, so destructive CLI operations are recoverable from the app's
  "Restore from backup" feature even if you skip the `backup` command.
- Use `streamdeck validate` to check a profile before and after a series of
  edits.

## Development

```bash
# Run tests
.venv/bin/pytest

# Lint
.venv/bin/ruff check .

# Type check
.venv/bin/mypy src

# All checks at once
.venv/bin/pytest --cov=streamdeck_cli --cov-report=term-missing
```

The project follows **strict TDD** — see `tests/` and the TDD commit history.

## Contributing

1. Fork the repo
2. Add a failing test for your feature (`pytest tests/`)
3. Make it pass
4. Open a PR

Please don't open a PR with code that doesn't have tests.

## License

MIT — see [LICENSE](LICENSE).

## Not affiliated

`streamdeck-cli` is an independent project. Elgato, Stream Deck, and the Stream
Deck SDK are trademarks of Corsair Gaming, Inc. This project is not endorsed
by or affiliated with Elgato or Corsair.
