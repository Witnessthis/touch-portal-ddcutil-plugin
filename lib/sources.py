"""Parses the plugin's "Video Sources" setting.

Keeps the mapping between a ddcutil input id (what `ddcutil setvcp 0x60` takes)
and a human-readable label entirely in Touch Portal's settings UI, instead of
hardcoding monitor-specific ids like 5/6/15 (HDMI 1/HDMI 2/DisplayPort on the
monitor this was written for) anywhere in this repo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: int
    label: str


def parse_sources(raw: str) -> list[Source]:
    """Parses comma-separated "id=label" pairs, e.g.
    "5=HDMI 1,6=HDMI 2,15=DisplayPort".

    A malformed entry, a duplicate id, or a duplicate label is silently
    skipped (the label is used as the action's choice value and must be
    unique to map back to an id) -- one bad entry in the setting should never
    take the whole plugin down.
    """
    seen_ids: set[int] = set()
    seen_labels: set[str] = set()
    sources: list[Source] = []
    for token in raw.split(","):
        token = token.strip()
        if not token or "=" not in token:
            continue
        raw_id, _, label = token.partition("=")
        raw_id = raw_id.strip()
        label = label.strip()
        if not raw_id or not label:
            continue
        try:
            source_id = int(raw_id, 10)
        except ValueError:
            continue
        if source_id in seen_ids or label in seen_labels:
            continue
        seen_ids.add(source_id)
        seen_labels.add(label)
        sources.append(Source(id=source_id, label=label))
    return sources
