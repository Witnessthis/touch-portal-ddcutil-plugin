"""Read/write access to the monitor's video input via `ddcutil`.

Uses VCP feature 0x60 ("Input Source Select"), the same feature the shell
scripts this plugin replaces (`change-display-input.sh` /
`init-video-source-tmp.sh`) used. current_source() always asks ddcutil for the
real, current value rather than trusting a cached copy, so the state stays
correct even when the input is changed by the monitor's own buttons or another
program -- never dependent on this plugin's own action being what triggered
the change.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

# Pinned to the AMD HDMI bus: the monitor is also reachable over the Nvidia
# passthrough card (/dev/i2c-10), which ddcutil would otherwise probe on every call.
DDCUTIL = ["ddcutil", "--bus", "1"]
INPUT_SOURCE_FEATURE = "0x60"

# ddcutil's --terse getvcp output is e.g. "VCP 60 SNC x05" -- the current value
# is whichever field looks like a hex byte, not a fixed field index, since the
# type field ("SNC", "C", "T", ...) varies by feature and monitor.
_HEX_TOKEN = re.compile(r"^x([0-9a-fA-F]+)$")


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    message: str


def current_source() -> int | None:
    """Decimal input source id ddcutil currently reports, or None if it can't
    be read (monitor asleep/disconnected, ddcutil not found, unexpected
    output, ...)."""
    try:
        result = subprocess.run(
            [*DDCUTIL, "--terse", "getvcp", INPUT_SOURCE_FEATURE],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    for field in result.stdout.split():
        match = _HEX_TOKEN.match(field)
        if match:
            return int(match.group(1), 16)
    return None


def set_source(source_id: int) -> CommandResult:
    """Switches the monitor to source_id (see the "Video Sources" setting)."""
    try:
        result = subprocess.run(
            [*DDCUTIL, "setvcp", INPUT_SOURCE_FEATURE, str(source_id)],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return CommandResult(ok=False, message=str(exc))
    if result.returncode != 0:
        return CommandResult(ok=False, message=result.stderr.strip() or result.stdout.strip())
    return CommandResult(ok=True, message=result.stdout.strip())
