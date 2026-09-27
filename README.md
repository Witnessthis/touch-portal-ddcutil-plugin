# touch-portal-ddcutil-plugin

A Touch Portal plugin for `ddcutil`: tracks which video input a monitor is
currently on and can switch it — read directly from the monitor over DDC/CI
every time, so it stays correct no matter what changes the input (a Touch
Portal button, the monitor's own buttons, another program, ...).

This replaces a pair of local shell scripts (`change-display-input.sh` /
`init-video-source-tmp.sh`) with a Touch Portal-native plugin: no tmp state
files, no separate init step — the daemon asks `ddcutil` directly and polls
periodically to catch changes made outside Touch Portal.

## Requirements

- Touch Portal.
- `ddcutil`, with permission to query/control the monitor over DDC/CI without
  `sudo` (typically `i2c` group membership or a udev rule — the same
  requirement the shell scripts this replaces already had).
- Python 3.
- A monitor whose VCP feature `0x60` ("Input Source Select") reports and
  accepts the values you want to switch between — check with:

  ```
  ddcutil --terse getvcp 0x60
  ```

## Setup

1. Run `install.sh`. It symlinks this repo into Touch Portal's `plugins`
   folder — no `sudo`.
2. Start Touch Portal, or restart it if it was already running, and accept
   the "trust this plugin" prompt.
3. Under Settings → Plugins → ddcutil Bridge, fill in:

   | Setting | Description |
   |---|---|
   | `Video Sources` | Comma-separated `id=label` pairs, e.g. `5=HDMI 1,6=HDMI 2,15=DisplayPort`. `id` is the decimal value `ddcutil setvcp 0x60` takes; `label` is what shows up in Touch Portal (must be unique). |

   Saving scans immediately and reports each source's status. Changes take
   effect without a restart. While `Video Sources` is empty or has no valid
   entries, the plugin does nothing: states stop updating and Change Input
   presses are ignored (see `daemon.log`). No states are removed, so buttons
   work again as soon as the setting is fixed.

## Wiring a monitor input button

A single button that both shows whether a given input is the active one and
switches to it when pressed:

1. Button → **On Event** tab → add event → **When Plugin State changes**.
2. State: `<label> status` (the source's label, taken from the Video Sources
   setting) — value is `attached`, `detached`, or `unknown` if ddcutil
   couldn't be read.
3. Condition: **changes to**. Value: `attached`.
4. Add an action to show that, e.g. **Change Button Visuals** → **Background
   Color** (pick your "active" color), or **Change Button Text**.
5. Repeat steps 1–4 with Condition **changes to**, Value `detached`, and a
   different color/text for the "not active" look.
6. Button → **On Press** tab → add action → **Change Input**.
7. Source: pick this button's label — the dropdown is populated from the
   Video Sources setting and stays in sync as it's edited, no restart needed.

**Change Input** also supports Touch Portal's **On Hold** tab, so a single
button can switch to one source on a short press and a different one on a
long press: add it under **On Press** with Source `HDMI 1`, say, and again
under **On Hold** with Source `DisplayPort` — each placement keeps its own
Source value.

A button doesn't need the state wiring (steps 1–5) to use the action — step
6–7 alone are enough for a plain input-switch button with no visual feedback.

### Why there's a short delay sometimes

Unlike libvirt (which has `virsh event --all --loop`), DDC/CI has no event
stream to watch. A Change Input button's own press updates state immediately,
but an input switch made some other way (the monitor's own buttons, another
program) is only noticed by a poll that runs every few seconds — so it can
take a moment for a button's look to catch up in that case.

## License

MIT — see [LICENSE](LICENSE).
