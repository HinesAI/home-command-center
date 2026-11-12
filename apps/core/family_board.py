"""Family group calendar + chores list for HCC.

Persists under /app/data. Kiosk and ICS feeds are read-only; mutations require
authenticated operator+ callers (mobile/web management UI).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

STORE_PATH = os.environ.get("HCC_FAMILY_BOARD_PATH", "/app/data/family-board.json")
_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty() -> dict[str, Any]:
    return {
        "version": 1,
        "updatedAt": _now_iso(),
        "events": [],
        "chores": [],
    }


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load() -> dict[str, Any]:
    with _lock:
        if not os.path.exists(STORE_PATH):
            data = _empty()
            _save(data)
            return data
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = _empty()
            _save(data)
            return data
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("events", [])
        data.setdefault("chores", [])
        data.setdefault("version", 1)
        return data


def _save(data: dict[str, Any]) -> None:
    data["updatedAt"] = _now_iso()
    _ensure_parent(STORE_PATH)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, STORE_PATH)


def snapshot(refresh_seconds: int = 30) -> dict[str, Any]:
    import caldav_client

    data = _load()
    local_events = list(data.get("events") or [])
    local_chores = list(data.get("chores") or [])
    source = "local"
    caldav_meta = {"enabled": False}

    if caldav_client.caldav_configured():
        remote = caldav_client.fetch_board()
        caldav_meta = {
            "enabled": True,
            "ok": remote.get("ok"),
            "error": remote.get("error"),
            "accountHint": remote.get("accountHint"),
        }
        # Prefer CalDAV when configured — Apple Calendar is source of truth.
        if remote.get("events") is not None:
            local_events = remote.get("events") or []
            source = "caldav"
        if remote.get("chores") is not None and (remote.get("chores") or remote.get("ok")):
            # If chores calendar configured, use it even when empty.
            if caldav_client.CALDAV_CHORES_CALENDAR:
                local_chores = remote.get("chores") or []
                source = "caldav"

    events = sorted(local_events, key=lambda e: (e.get("start") or "", e.get("title") or ""))
    chores = sorted(
        local_chores,
        key=lambda c: (bool(c.get("done")), c.get("due") or "9999", c.get("title") or ""),
    )
    open_chores = [c for c in chores if not c.get("done")]

    # Merge Reminders / chores into the Family calendar as reminder items.
    merged = list(events)
    seen_ids = {e.get("id") for e in merged if e.get("id")}
    for chore in open_chores:
        due = str(chore.get("due") or "").strip()
        if not due:
            continue
        item_id = chore.get("id") or f"reminder:{chore.get('title')}:{due}"
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        all_day = "T" not in due
        start = due if "T" in due else due[:10]
        end = start
        merged.append(
            {
                "id": item_id,
                "title": chore.get("title") or "Reminder",
                "start": start,
                "end": end,
                "allDay": all_day,
                "location": chore.get("assignee") or None,
                "notes": chore.get("notes"),
                "source": chore.get("source") or "reminder",
                "kind": "reminder",
                "recurring": bool(chore.get("recurring")),
            }
        )
    merged.sort(key=lambda e: (e.get("start") or "", 0 if e.get("kind") == "reminder" else 1, e.get("title") or ""))

    return {
        "ok": True,
        "generatedAt": _now_iso(),
        "updatedAt": data.get("updatedAt"),
        "refreshSeconds": refresh_seconds,
        "source": source,
        "caldav": caldav_meta,
        "writableLocally": source != "caldav",
        "events": merged,
        "chores": chores,
        "summary": {
            "eventCount": len(events),
            "choreCount": len(chores),
            "openChoreCount": len(open_chores),
            "upcomingEventCount": len(_upcoming_events(merged, limit=50)),
        },
        "upcoming": _upcoming_events(merged, limit=12),
        "openChores": open_chores[:20],
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _upcoming_events(events: list[dict], limit: int = 12) -> list[dict]:
    now = datetime.now(timezone.utc)
    upcoming = []
    for event in events:
        start = _parse_dt(event.get("start"))
        end = _parse_dt(event.get("end")) or start
        if end and end < now:
            continue
        upcoming.append(event)
    upcoming.sort(key=lambda e: e.get("start") or "")
    return upcoming[:limit]


def _clean_text(value: Any, field: str, max_len: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text[:max_len]


def add_event(payload: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    title = _clean_text(payload.get("title"), "title")
    start = str(payload.get("start") or "").strip()
    if not start:
        raise ValueError("start is required (ISO datetime or YYYY-MM-DD)")
    end = str(payload.get("end") or "").strip() or None
    location = str(payload.get("location") or "").strip()[:200] or None
    notes = str(payload.get("notes") or "").strip()[:2000] or None
    all_day = bool(payload.get("allDay"))

    event = {
        "id": "evt_" + uuid.uuid4().hex[:12],
        "title": title,
        "start": start,
        "end": end,
        "allDay": all_day,
        "location": location,
        "notes": notes,
        "createdAt": _now_iso(),
        "createdBy": actor or "unknown",
        "updatedAt": _now_iso(),
    }
    with _lock:
        data = _load()
        data["events"].append(event)
        _save(data)
    return event


def update_event(event_id: str, payload: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    with _lock:
        data = _load()
        for event in data["events"]:
            if event.get("id") != event_id:
                continue
            if "title" in payload:
                event["title"] = _clean_text(payload.get("title"), "title")
            if "start" in payload:
                start = str(payload.get("start") or "").strip()
                if not start:
                    raise ValueError("start is required")
                event["start"] = start
            if "end" in payload:
                end = str(payload.get("end") or "").strip()
                event["end"] = end or None
            if "allDay" in payload:
                event["allDay"] = bool(payload.get("allDay"))
            if "location" in payload:
                loc = str(payload.get("location") or "").strip()[:200]
                event["location"] = loc or None
            if "notes" in payload:
                notes = str(payload.get("notes") or "").strip()[:2000]
                event["notes"] = notes or None
            event["updatedAt"] = _now_iso()
            event["updatedBy"] = actor or "unknown"
            _save(data)
            return event
    raise KeyError("event not found")


def delete_event(event_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["events"])
        data["events"] = [e for e in data["events"] if e.get("id") != event_id]
        if len(data["events"]) == before:
            return False
        _save(data)
        return True


def add_chore(payload: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    title = _clean_text(payload.get("title"), "title")
    assignee = str(payload.get("assignee") or "").strip()[:80] or None
    due = str(payload.get("due") or "").strip() or None
    notes = str(payload.get("notes") or "").strip()[:1000] or None
    chore = {
        "id": "chore_" + uuid.uuid4().hex[:12],
        "title": title,
        "assignee": assignee,
        "due": due,
        "notes": notes,
        "done": False,
        "createdAt": _now_iso(),
        "createdBy": actor or "unknown",
        "updatedAt": _now_iso(),
    }
    with _lock:
        data = _load()
        data["chores"].append(chore)
        _save(data)
    return chore


def update_chore(chore_id: str, payload: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    with _lock:
        data = _load()
        for chore in data["chores"]:
            if chore.get("id") != chore_id:
                continue
            if "title" in payload:
                chore["title"] = _clean_text(payload.get("title"), "title")
            if "assignee" in payload:
                assignee = str(payload.get("assignee") or "").strip()[:80]
                chore["assignee"] = assignee or None
            if "due" in payload:
                due = str(payload.get("due") or "").strip()
                chore["due"] = due or None
            if "notes" in payload:
                notes = str(payload.get("notes") or "").strip()[:1000]
                chore["notes"] = notes or None
            if "done" in payload:
                chore["done"] = bool(payload.get("done"))
                if chore["done"]:
                    chore["completedAt"] = _now_iso()
                    chore["completedBy"] = actor or "unknown"
                else:
                    chore.pop("completedAt", None)
                    chore.pop("completedBy", None)
            chore["updatedAt"] = _now_iso()
            chore["updatedBy"] = actor or "unknown"
            _save(data)
            return chore
    raise KeyError("chore not found")


def delete_chore(chore_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["chores"])
        data["chores"] = [c for c in data["chores"] if c.get("id") != chore_id]
        if len(data["chores"]) == before:
            return False
        _save(data)
        return True


def _ics_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_stamp(value: str | None, all_day: bool) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if all_day or len(raw) <= 10:
        day = raw[:10].replace("-", "")
        if len(day) == 8 and day.isdigit():
            return day
    dt = _parse_dt(raw)
    if not dt:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render_ics() -> str:
    """Read-only ICS feed — subscribe from Apple Calendar (view only; manage via HCC Family page)."""
    data = _load()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Home Command Center//Family Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:HCC Family",
    ]
    for event in data.get("events") or []:
        uid = event.get("id") or uuid.uuid4().hex
        all_day = bool(event.get("allDay"))
        dtstart = _ics_stamp(event.get("start"), all_day)
        if not dtstart:
            continue
        dtend = _ics_stamp(event.get("end"), all_day) or dtstart
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}@hcc.family")
        lines.append(f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        if all_day or len(dtstart) == 8:
            lines.append(f"DTSTART;VALUE=DATE:{dtstart[:8]}")
            lines.append(f"DTEND;VALUE=DATE:{dtend[:8]}")
        else:
            lines.append(f"DTSTART:{dtstart}")
            lines.append(f"DTEND:{dtend}")
        lines.append(f"SUMMARY:{_ics_escape(event.get('title') or 'Event')}")
        if event.get("location"):
            lines.append(f"LOCATION:{_ics_escape(event['location'])}")
        if event.get("notes"):
            lines.append(f"DESCRIPTION:{_ics_escape(event['notes'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
