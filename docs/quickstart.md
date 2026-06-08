# Quickstart

Real, working examples against a live Stream Deck 7.3.1 install on macOS.
Each block was run as part of writing this doc — the output is not fabricated.

## 0. Install

```sh
git clone https://github.com/tylerdotai/streamdeck-cli
cd streamdeck-cli
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/streamdeck --version
# streamdeck, version 0.1.0
```

## 1. See what you've got

```sh
.venv/bin/streamdeck list-profiles
# Default Profile       20GBD9901   /Users/soup/Library/Application Support/com.elgato.StreamDeck/ProfilesV3/92B4842D-…3733A63927AE.sdProfile

.venv/bin/streamdeck list-pages
# ff56cdd9-5ca7-4e39-927d-2390318b62f7    (unnamed) [current]
# c3131e37-3d49-4735-953a-fe3785d94a59    (unnamed)

.venv/bin/streamdeck list-devices
# (lists connected Stream Deck hardware, e.g. "Stream Deck XL (20GBD9901)")
```

## 2. Render a page as YAML (round-trip the manifest)

The first page UUID came from `list-pages` above. `show-spec` turns a
binary-ish JSON manifest into a YAML spec you can read, edit, and commit.

```sh
.venv/bin/streamdeck show-spec ff56cdd9-5ca7-4e39-927d-2390318b62f7
```

```yaml
name: (unnamed)
controllers:
  encoder:
    actions:
      "0,0":
        title: Undo/Redo
        icon: Images/97WWHHJRAT34T7TC9VPFNTCCWOZ.png
      "1,0":
        title:  System Volume
      "2,0":
        title: SD+ Brightness
  keypad:
    actions:
      "0,0":
        title: Apps
      "1,0":
        title: Links
      "1,1":
        title: Screenshot
      "2,0":
        title: Emojis
      "2,1":
        title: Screen Off
```

Save it to a file so you can edit it:

```sh
.venv/bin/streamdeck show-spec ff56cdd9-5ca7-4e39-927d-2390318b62f7 -o pages/main.yaml
```

## 3. Edit a spec, then materialize it as a new page

```sh
$EDITOR pages/coding.yaml   # see Appendix A in schema.md for the format
.venv/bin/streamdeck new-page --from-yaml pages/coding.yaml --icons-dir pages/icons
# created page 4f8a1b2c-…    (name: "Coding")
```

## 4. Assign an icon to a key

```sh
.venv/bin/streamdeck set-icon <page-uuid> 0,0 ~/Pictures/vscode.png
# wrote Images/3D7FK9X2WV…png

.venv/bin/streamdeck remove-icon <page-uuid> 0,0
# cleared action 0,0 icon (PNG kept on disk)
```

## 5. Export the whole profile

`export` writes the entire profile (manifest + all pages + all images,
base64-embedded) as a single JSON or YAML file. This is what you commit
to git and share with friends.

```sh
PROFDIR="$HOME/Library/Application Support/com.elgato.StreamDeck/ProfilesV3/92B4842D-…3733A63927AE.sdProfile"

.venv/bin/streamdeck export -o profile.yaml --profile-dir "$PROFDIR"
# wrote profile.yaml (yaml)

wc -l profile.yaml
# 366 profile.yaml
```

`profile.yaml` opens to:

```yaml
name: Default Profile
device:
  Model: 20GBD9901
  UUID: '@(1)[4057/132/A00WA5321KRQSZ]'
pages:
- uuid: ff56cdd9-5ca7-4e39-927d-2390318b62f7
  manifest:
    Controllers:
    - Actions:
        0,0:
          ActionID: b82628ed-58b5-4115-b031-985f5c35eb19
          Name: Hotkey
          Plugin:
            UUID: com.elgato.streamdeck.system.hotkey
          Settings:
            Hotkeys:
            - KeyCtrl: true
              NativeCode: 90
              # …
  images:
    97WWHHJRAT34T7TC9VPFNTCCWOZ.png: "<base64 bytes>"
```

## 6. Diff two profiles before merging

```sh
# Clone the export, edit it, then see what would change
cp profile.yaml profile-friend.yaml
$EDITOR profile-friend.yaml

.venv/bin/streamdeck diff profile.yaml profile-friend.yaml
# added:   [ {name: "Gaming", uuid: "..."} ]
# removed: []
# modified: [ {name: "Coding", uuid: "..."} ]
```

## 7. Validate the live install

```sh
.venv/bin/streamdeck validate
# WARN: orphan page directory 'FF56CDD9-…' (not in active pages list)
# WARN: orphan page directory '8DBCFF3D-…' (not in active pages list)
# …
```

Orphan page directories are normal — Stream Deck 7.x never deletes them
when you remove a page from rotation. The CLI flags them so you can
clean them up if you want to.

## 8. Back up before you do something dangerous

```sh
.venv/bin/streamdeck backup -o ~/Desktop/profile-$(date +%Y%m%d).zip
# wrote 1.4 MB to ~/Desktop/profile-20260608.zip

.venv/bin/streamdeck restore ~/Desktop/profile-20260608.zip
# (confirms before overwriting)
```

## 9. Use it from an MCP client

Add to your MCP client config (Claude Code, Cursor, etc.):

```json
{
  "mcpServers": {
    "streamdeck": {
      "command": "streamdeck-mcp"
    }
  }
}
```

You can now do things like:

> "List my Stream Deck profiles"
> "Create a new page called Coding with VS Code, Terminal, and Spotify on the top row"
> "Export the current profile to a YAML file I can commit"

See [`docs/schema.md`](schema.md#appendix-a-yaml-page-spec-format) for the
full YAML spec format and JSON/YAML export format reference.
