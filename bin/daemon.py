#!/usr/bin/env python3
"""Entry point Touch Portal launches (via entry.tp's plugin_start_cmd).

Lifecycle:
  1. Connect + pair with Touch Portal immediately -- no local config file is
     needed or read to do this.
  2. Touch Portal sends the plugin's settings (entry.tp's "settings" array,
     filled in under Settings -> Plugins -> ddcutil Bridge) right after
     pairing, and again whenever they're saved. Once "Video Sources" parses to
     at least one source, and whenever it changes after that, a full rescan
     runs: ask ddcutil which input is currently active, and push a state for
     every configured source. While it's empty or has no valid entries, the
     plugin is idle: no state is updated, Change Input presses are ignored,
     and every state is left exactly as it is (nothing is removed), so
     buttons pick up where they left off once the setting is fixed.
  3. Unlike libvirt (which has `virsh event --all --loop`), ddcutil/DDC-CI has
     no event stream -- the monitor's own buttons or another program can
     change the input with nothing telling this process it happened. So a
     background loop requests a rescan every POLL_SECONDS, on top of the
     rescan already requested after every settings change and Change Input
     action.
  4. Handle the "Change Input" action, declared in entry.tp: its "Source"
     field is a `choice` list of the configured labels, kept in sync via a
     `choiceUpdate` message sent on every rescan -- the action-data equivalent
     of createState/removeState above. This action is a plain, always-fires
     action -- for a button that only does something on a genuine long press
     (or only on a quick tap, suppressing a long press), see the separate
     touch-portal-holdtiming-plugin project instead. Touch Portal has no way
     to gate a plain action by hold duration (there's no minimum enforced --
     see lib/tp_client.py's history for why an in-plugin attempt at this was
     abandoned), so this plugin no longer tries.
  5. Exit cleanly on Touch Portal's "closePlugin" message, the connection to
     it dropping, or SIGTERM/SIGINT.

This process's only side effect outside itself is the "Change Input" action
running `ddcutil setvcp` -- every other code path only reads.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import ddcutil_control  # noqa: E402
from lib.sources import Source, parse_sources  # noqa: E402
from lib.tp_client import DEFAULT_PORT, TouchPortalClient  # noqa: E402

LOG_PATH = REPO_ROOT / "daemon.log"
DEBOUNCE_SECONDS = 0.5
POLL_SECONDS = 5  # catches input changes made by the monitor's own buttons

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("ddcutilbridge")


def load_plugin_id() -> str:
    """The plugin's pairing id lives in entry.tp -- that's the only place Touch
    Portal itself reads it from, so it's the single source of truth."""
    entry = json.loads((REPO_ROOT / "entry.tp").read_text())
    return entry["id"]


SOURCE_STATE_PREFIX = "ddcutilbridge.source."


def source_state_id(source_id: int) -> str:
    return f"{SOURCE_STATE_PREFIX}{source_id}"


CHANGE_INPUT_ACTION_ID = "ddcutilbridge.action.changeinput"
CHANGE_INPUT_SOURCE_FIELD_ID = "ddcutilbridge.action.changeinput.source"

# Must match entry.tp's settings[].name exactly -- that field doubles as the id
# Touch Portal uses as the key in its "settings"/"info" messages.
SETTING_VIDEO_SOURCES = "Video Sources"


@dataclass(frozen=True)
class Settings:
    """One consistent set of settings. Replaced as a whole on every change, so
    a rescan that grabs it once can't see half of an update."""

    sources: tuple[Source, ...] = ()

    def problem(self) -> str | None:
        """Why these settings can't be used, or None if they can."""
        if not self.sources:
            return f"{SETTING_VIDEO_SOURCES!r} has no valid entries"
        return None


class Bridge:
    def __init__(self, tp_port: int) -> None:
        self.settings = Settings()
        self.tp = TouchPortalClient(
            plugin_id=load_plugin_id(),
            port=tp_port,
            on_close=self._on_tp_close,
            on_action=self._on_action,
            on_settings=self._on_settings,
        )
        # Only touched by rescan(), which only ever runs on the rescan worker.
        self._known_states: set[str] = set()
        self._change_lock = threading.Lock()
        self._rescan_event = threading.Event()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self._rescan_event.set()

    def _on_tp_close(self) -> None:
        log.info("Touch Portal asked the plugin to close.")
        self.stop()

    def _on_settings(self, values: dict[str, str]) -> None:
        raw = values.get(SETTING_VIDEO_SOURCES, "")
        new = Settings(sources=tuple(parse_sources(raw)))
        changed = new != self.settings
        self.settings = new

        log.info("settings received: Video Sources=%r -> %s", raw,
                  [(source.id, source.label) for source in new.sources])

        problem = new.problem()
        if problem:
            log.warning(
                "%s -- the plugin is idle, leaving every state as it is, until "
                "that's fixed under Touch Portal Settings -> Plugins -> "
                "ddcutil Bridge.",
                problem,
            )
            return
        if changed:
            self.request_rescan()

    def _on_action(self, action_id: str, data: dict[str, str]) -> None:
        if action_id == CHANGE_INPUT_ACTION_ID:
            self._on_change_input_action(data)
        else:
            log.warning("received unknown action id %r", action_id)

    def _on_change_input_action(self, data: dict[str, str]) -> None:
        problem = self.settings.problem()
        if problem:
            log.warning("Change Input action ignored -- %s", problem)
            return
        label = data.get(CHANGE_INPUT_SOURCE_FIELD_ID, "")
        # Run off the Touch Portal read thread, same reason as the libvirt
        # plugin's power/USB actions: ddcutil calls can be slow, and this
        # callback runs on the thread that reads from Touch Portal.
        threading.Thread(
            target=self._run_change_input, args=(label,), daemon=True
        ).start()

    def _run_change_input(self, label: str) -> None:
        # Serialize presses, so two quick presses can't interleave two setvcp
        # calls against the same monitor.
        with self._change_lock:
            self._run_change_input_locked(label)

    def _run_change_input_locked(self, label: str) -> None:
        settings = self.settings
        problem = settings.problem()
        if problem:
            log.warning("Change Input action ignored -- %s", problem)
            return

        source = next((s for s in settings.sources if s.label == label), None)
        if source is None:
            log.error("Change Input action ignored -- unknown source %r", label)
            return

        log.info("Change Input action -> %s (id %s)", source.label, source.id)
        result = ddcutil_control.set_source(source.id)
        if result.ok:
            log.info("ddcutil setvcp 0x60 %s succeeded: %s", source.id, result.message)
        else:
            log.error("ddcutil setvcp 0x60 %s failed: %s", source.id, result.message)

        # The poll loop would notice the change on its own eventually, but
        # request a rescan directly too so the state reflects the command's
        # outcome without waiting up to POLL_SECONDS for it.
        self.request_rescan()

    def start(self) -> None:
        log.info("Connecting to Touch Portal at %s:%s", self.tp.host, self.tp.port)
        self.tp.connect_and_pair()

        # The first rescan is requested by _on_settings once Touch Portal has
        # sent the settings, and goes through the worker like every later one.
        threading.Thread(target=self._rescan_worker, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def rescan(self) -> None:
        settings = self.settings
        problem = settings.problem()
        if problem:
            log.info("rescan skipped -- %s", problem)
            return

        current_id = ddcutil_control.current_source()
        current: set[str] = set()
        labels: list[str] = []
        for source in settings.sources:
            state_id = source_state_id(source.id)
            current.add(state_id)
            labels.append(source.label)
            if current_id is None:
                status = "unknown"
            elif current_id == source.id:
                status = "attached"
            else:
                status = "detached"
            self._set_state(state_id, f"{source.label} status", status)
            log.info("source %s (id %s) -> %s", source.label, source.id, status)

        # A source no longer in the setting has nothing left to show -- remove
        # its state so Touch Portal's list of states matches the setting.
        for state_id in sorted(self._known_states - current):
            self.tp.remove_state(state_id)
            self._known_states.discard(state_id)
            log.info("removed state %s -- no longer in Video Sources", state_id)

        # Keeps the Change Input action's "Source" dropdown in sync with the
        # setting, the same way createState/removeState above keep the state
        # list in sync.
        self.tp.update_choices(CHANGE_INPUT_SOURCE_FIELD_ID, labels)

    def _set_state(self, state_id: str, description: str, value: str) -> None:
        if state_id not in self._known_states:
            # Created empty on purpose: buttons react to a *change* of this
            # state, so the first real value must always count as one --
            # otherwise a freshly started Touch Portal would never update them.
            self.tp.create_state(state_id, description, "")
            self._known_states.add(state_id)
        self.tp.update_state(state_id, value)

    def request_rescan(self) -> None:
        self._rescan_event.set()

    def _rescan_worker(self) -> None:
        """Coalesces bursts of rescan requests into a single rescan each."""
        while not self._stop_event.is_set():
            self._rescan_event.wait()
            if self._stop_event.is_set():
                return
            self._rescan_event.clear()
            time.sleep(DEBOUNCE_SECONDS)  # let a burst of requests settle
            self._rescan_event.clear()
            try:
                self.rescan()
            except Exception:
                log.exception("rescan failed")

    def _poll_loop(self) -> None:
        """ddcutil has no event stream to watch, so this is what notices an
        input change made by the monitor's own buttons or another program."""
        while not self._stop_event.wait(POLL_SECONDS):
            self.request_rescan()

    def run_forever(self) -> None:
        self._stop_event.wait()
        self.tp.close()


def main() -> None:
    tp_port = int(os.environ.get("TP_PORT", DEFAULT_PORT))
    bridge = Bridge(tp_port)

    def handle_signal(signum, frame):
        log.info("received signal %s, shutting down", signum)
        bridge.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    bridge.start()
    bridge.run_forever()


if __name__ == "__main__":
    main()
