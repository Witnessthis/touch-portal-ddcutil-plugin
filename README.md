# touch-portal-ddcutil-plugin

A Touch Portal plugin for `ddcutil`: tracks which video input a monitor is
currently on and can switch it — read directly from the monitor over DDC/CI.

This replaces a pair of local shell scripts (`change-display-input.sh` /
`init-video-source-tmp.sh`) with a Touch Portal-native plugin: no tmp state
files, no separate init step — the daemon asks `ddcutil` directly at startup
and after every input change it makes.

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

A button doesn't need the state wiring (steps 1–5) to use the action — step
6–7 alone are enough for a plain input-switch button with no visual feedback.

For a button where a short tap does one thing and a genuine long press does
something else entirely (e.g. tap to switch inputs, long-press to run a
different plugin's action), see the separate `touch-portal-holdtiming-plugin`
project — Touch Portal only allows a single action in a button's **On Hold**
tab, so gating this plugin's own action by hold duration doesn't work; a
dedicated timing plugin paired with plain actions like this one's does.

### Why a button can show the wrong input

Unlike libvirt (which has `virsh event --all --loop`), DDC/CI has no event
stream to watch, and switching inputs fires no DRM uevent either. The plugin
deliberately doesn't poll the monitor over I2C, so an input switch made some
other way (the monitor's own buttons, another program) isn't shown until the
next Change Input press, settings change, or Touch Portal restart.

## License

MIT — see [LICENSE](LICENSE).
