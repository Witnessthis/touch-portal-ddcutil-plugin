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

A button doesn't need the state wiring (steps 1–5) to use the action — step
6–7 alone are enough for a plain input-switch button with no visual feedback.

## Building a tap/long-press button

**Change Input (Before Threshold)** and **Change Input (After Threshold)** are
separate actions for a button where a short tap switches to one source and a
genuine long press does something else entirely — e.g. tap to switch inputs,
long-press to run a different plugin's action (say, `libvirt Bridge`'s VM
Power). Unlike a plain button press, Touch Portal cannot cancel an action once
it's fired, so these two run on *release*, gated by how long the button was
actually held — placed under the button's **On Hold** tab (never **On Press**,
which fires unconditionally, instantly, with no way to gate it):

1. Button → **On Hold** tab → add action → **Change Input (Before Threshold)**.
2. Source: same as the plain action.
3. Threshold (ms): how long the button must be held for this *not* to count as
   a tap. Default `1000`.
4. Add a second action, **Change Input (After Threshold)**, with the same
   Source and the *same* Threshold value.

With matching thresholds, releasing before it fires the Before action and
releasing at/after it fires the After action — never both, never neither. If
you give them different thresholds you'll get a gap (releasing in between
fires nothing) or an overlap (releasing in between fires both) — the plugin
doesn't know the other placement's value, so keeping them in sync is on you.
Either one works standalone too, e.g. a button with only **Change Input
(After Threshold)** and nothing under On Press just does nothing on a quick
tap.

While held past its own threshold, **Change Input (After Threshold)** flips
state `<label> long-press active` (the same label as its status state) to `1`
(back to `0` on release) — wire whatever visual feedback you want off it (e.g.
**On Event** → state changes to `1` → **Change Button Visuals** → **Icon** →
Full Size Icon), entirely your choice; the plugin only provides the signal.
**Before Threshold** has no such state — there's nothing meaningful to show
mid-hold for it.

Nothing stops you pairing a Before/After pair from *different* plugins on one
button, as long as both sides use the same threshold — e.g. this plugin's
Change Input (Before Threshold) for a quick tap, and another plugin's After
Threshold action for a long press. Neither plugin needs to know the other
exists; both just independently compare the same release time against the
same number.

### Why there's a short delay sometimes

Unlike libvirt (which has `virsh event --all --loop`), DDC/CI has no event
stream to watch. A Change Input button's own press updates state immediately,
but an input switch made some other way (the monitor's own buttons, another
program) is only noticed by a poll that runs every few seconds — so it can
take a moment for a button's look to catch up in that case.

## License

MIT — see [LICENSE](LICENSE).
