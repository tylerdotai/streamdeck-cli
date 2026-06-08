# Stream Deck On-Disk Schema (Reverse-Engineered)

The Elgato Stream Deck desktop app (tested on **7.3.1**, build 22604) stores all
profile data as JSON on the local filesystem. There is no official schema
documentation, so this file documents the layout that `streamdeck-cli`
reverse-engineers and works with.

## Locations

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/com.elgato.StreamDeck/` |
| Windows | `%APPDATA%\Elgato\StreamDeck\` |

```
<root>/
├── ProfilesV3/
│   └── <profile-uuid>.sdProfile/
│       ├── manifest.json
│       └── Profiles/
│           ├── <page-uuid-1>/
│           │   ├── manifest.json
│           │   └── Images/
│           ├── <page-uuid-2>/
│           │   └── ...
│           └── <page-uuid-N>/
│               └── ...
├── BackupV3/   # auto-generated .streamDeckProfilesBackup files (zip)
├── Plugins/    # installed plugins (sdPlugin bundles)
└── Marketplace/# plugin store cache
```

## Profile manifest

`ProfilesV3/<profile-uuid>.sdProfile/manifest.json`

```json
{
  "Name": "Default Profile",
  "Version": "3.0",
  "Device": {
    "Model": "20GBD9901",          // Stream Deck XL
    "UUID": "@(1)[4057/132/A00WA5321KRQSZ]"
  },
  "Pages": {
    "Current": "ff56cdd9-5ca7-4e39-927d-2390318b62f7",
    "Default": "8dbcff3d-e4d6-45ee-881d-1ed8016c300b",
    "Pages": [
      "ff56cdd9-5ca7-4e39-927d-2390318b62f7",
      "c3131e37-3d49-4735-953a-fe3785d94a59"
    ]
  }
}
```

**Note on case:** UUIDs in `Pages.Pages` are **lowercase**; the corresponding
directories on disk are **uppercase**. `streamdeck-cli` normalizes this.

**Note on `Default`:** Stream Deck allows `Default` to point to a UUID that is
not in the active `Pages.Pages` list — this happens when a page has been
removed from rotation. The CLI's `validate` command reports this as an info
condition (a no-op), not an error.

## Page manifest

`ProfilesV3/<profile-uuid>.sdProfile/Profiles/<page-uuid>/manifest.json`

```json
{
  "Name": "",
  "Icon": "",
  "Controllers": [
    {
      "Type": "Keypad",
      "Actions": {
        "0,0": { /* action object */ },
        "1,0": { /* action object */ }
      }
    },
    {
      "Type": "Encoder",
      "Actions": {
        "0,0": { /* encoder action object */ }
      }
    }
  ]
}
```

Two controllers per page: `Keypad` (the physical keys) and `Encoder` (the
dials, on the XL and Plus).

`Actions` is `null` for an empty page, or a dict keyed by `"col,row"` for
Keypad actions and `"0,row"` for Encoder actions.

## Action object (Keypad)

```json
{
  "ActionID": "b82628ed-58b5-4115-b031-985f5c35eb19",
  "Name": "Hotkey",
  "UUID": "com.elgato.streamdeck.system.hotkey",
  "Plugin": {
    "Name": "Activate a Key Command",
    "UUID": "com.elgato.streamdeck.system.hotkey",
    "Version": "1.0"
  },
  "LinkedTitle": true,
  "State": 0,
  "States": [
    { "Title": "Undo/Redo" }
  ],
  "Settings": {
    "Coalesce": true,
    "Hotkeys": [
      {
        "KeyCmd": false,
        "KeyCtrl": true,
        "KeyModifiers": 2,
        "KeyOption": false,
        "KeyShift": false,
        "NativeCode": 90,
        "QTKeyCode": 90,
        "VKeyCode": 90
      }
    ]
  },
  "Encoder": {
    "Icon": "Images/97WWHHJRAT34T7TC9VPFNTCCWOZ.png"
  }
}
```

Common plugin UUIDs (system plugins that ship with the Stream Deck app):

| UUID | Name |
|---|---|
| `com.elgato.streamdeck.system.hotkey` | Activate a Key Command |
| `com.elgato.streamdeck.system.multimedia` | Multimedia |
| `com.elgato.streamdeck.system.keybrightness` | Brightness |
| `com.elgato.streamdeck.system.website` | Website |
| `com.elgato.streamdeck.system.timer` | Timer |
| `com.elgato.streamdeck.system.switchprofile` | Switch Profile |

## Device model numbers

| Model | Device |
|---|---|
| `20GAI9901` | Stream Deck (Gen 1, 15-key) |
| `20GBD9901` | Stream Deck XL (Gen 1) |
| `20GAT9901` | Stream Deck Plus |
| `20GAS9901` | Stream Deck Studio |
| `20GAK9901` | Stream Deck Pedal |
| `20GAL9901` | Stream Deck Neo |

## Known quirks

- The app **picks up manifest changes live** — no restart required for new
  pages, but you may need to toggle the Stream Deck app to the next page and
  back to see the new one in the editor.
- The app writes a snapshot to `BackupV3/` on every change, so destructive
  CLI actions are recoverable via the app's built-in "Restore from backup"
  feature even without our `backup` command.
- Image files in `Images/` are PNGs at the device's native resolution
  (72×72 for the original, 96×96 for XL, 120×120 for Plus).

## How this schema was discovered

`streamdeck-cli` is not affiliated with Elgato. The schema was reverse-engineered
by capturing JSON files from a real Stream Deck 7.3.1 install and observing how
the app reacts to edits. It is a best-effort description of an undocumented
format, and may not match every version. Please open an issue if you find
something we've missed.
