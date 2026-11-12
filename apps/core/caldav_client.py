"""Minimal CalDAV client (stdlib) for reading VEVENT / VTODO from Apple-friendly servers.

Apple Calendar/Reminders write directly to CalDAV (Radicale/Nextcloud).
HCC only reads for kiosk/Family display — no separate login required to manage items.
"""

from __future__ import annotations

import base64
import os
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

# Expand recurring events/todos across this window for month + agenda views.
# Default ~13 months ahead so perpetual daily/weekly series keep filling as you page months.
_EXPAND_PAST_DAYS = int(os.environ.get("HCC_CALDAV_EXPAND_PAST_DAYS", "40"))
_EXPAND_FUTURE_DAYS = int(os.environ.get("HCC_CALDAV_EXPAND_FUTURE_DAYS", "400"))

_ICAL_WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

CALDAV_URL = os.environ.get("HCC_CALDAV_URL", "").strip()
CALDAV_USER = os.environ.get("HCC_CALDAV_USER", "").strip()
CALDAV_PASSWORD = os.environ.get("HCC_CALDAV_PASSWORD", "").strip()
# Collection URLs (full path or path relative to CALDAV_URL)
CALDAV_EVENTS_CALENDAR = os.environ.get("HCC_CALDAV_EVENTS_CALENDAR", "").strip()
CALDAV_CHORES_CALENDAR = os.environ.get("HCC_CALDAV_CHORES_CALENDAR", "").strip()
CALDAV_VERIFY_TLS = os.environ.get("HCC_CALDAV_VERIFY_TLS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def caldav_configured() -> bool:
    return bool(CALDAV_URL and CALDAV_USER and (CALDAV_EVENTS_CALENDAR or CALDAV_CHORES_CALENDAR))


def reload_configuration() -> None:
    global CALDAV_URL, CALDAV_USER, CALDAV_PASSWORD
    global CALDAV_EVENTS_CALENDAR, CALDAV_CHORES_CALENDAR, CALDAV_VERIFY_TLS
    CALDAV_URL = os.environ.get("HCC_CALDAV_URL", "").strip()
    CALDAV_USER = os.environ.get("HCC_CALDAV_USER", "").strip()
    CALDAV_PASSWORD = os.environ.get("HCC_CALDAV_PASSWORD", "").strip()
    CALDAV_EVENTS_CALENDAR = os.environ.get("HCC_CALDAV_EVENTS_CALENDAR", "").strip()
    CALDAV_CHORES_CALENDAR = os.environ.get("HCC_CALDAV_CHORES_CALENDAR", "").strip()
    CALDAV_VERIFY_TLS = os.environ.get("HCC_CALDAV_VERIFY_TLS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _auth_header() -> str:
    token = base64.b64encode(f"{CALDAV_USER}:{CALDAV_PASSWORD}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _absolute(url_or_path: str) -> str:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        return url_or_path
    base = CALDAV_URL if CALDAV_URL.endswith("/") else CALDAV_URL + "/"
    return urljoin(base, url_or_path.lstrip("/"))


def _request(method: str, url: str, body: bytes | None = None, content_type: str | None = None, depth: str = "1") -> bytes:
    headers = {
        "Authorization": _auth_header(),
        "Depth": depth,
        "User-Agent": "HCC-FamilyBoard/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    context = None
    if url.startswith("https://") and not CALDAV_VERIFY_TLS:
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=20, context=context) as resp:
        return resp.read()


def _report_calendar(calendar_url: str) -> str:
    """CalDAV calendar-query returning calendar-data for all objects."""
    body = b"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT"/>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>
"""
    # Also try without filter restriction by doing a second query for VTODO if needed — combined query:
    body = b"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR"/>
  </C:filter>
</C:calendar-query>
"""
    raw = _request(
        "REPORT",
        _absolute(calendar_url),
        body=body,
        content_type="application/xml; charset=utf-8",
        depth="1",
    )
    return raw.decode("utf-8", errors="replace")


def _extract_calendar_data_blobs(multistatus_xml: str) -> list[str]:
    blobs: list[str] = []
    # Namespace-agnostic scrape for calendar-data text
    for match in re.finditer(
        r"<(?:[\w-]+:)?calendar-data[^>]*>(.*?)</(?:[\w-]+:)?calendar-data>",
        multistatus_xml,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = match.group(1)
        text = (
            text.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&#13;", "")
            .strip()
        )
        if "BEGIN:VCALENDAR" in text:
            blobs.append(text)
    return blobs


def _unfold_ics(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))


def _parse_prop_line(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            pk, pv = part.split("=", 1)
            params[pk.upper()] = pv
        else:
            params[part.upper()] = ""
    return name, params, value.strip()


def _parse_component(block: str) -> dict[str, Any]:
    """Parse one VEVENT/VTODO block into props + param maps + multi-value fields."""
    props: dict[str, str] = {}
    params: dict[str, dict[str, str]] = {}
    multi: dict[str, list[str]] = {}
    for line in block.split("\n"):
        parsed = _parse_prop_line(line)
        if not parsed:
            continue
        name, line_params, value = parsed
        props[name] = value
        params[name] = line_params
        multi.setdefault(name, []).append(value)
    return {"props": props, "params": params, "multi": multi}


def _iter_components(ics_text: str, name: str) -> list[dict[str, Any]]:
    text = _unfold_ics(ics_text)
    pattern = re.compile(
        rf"BEGIN:{name}\n(.*?)END:{name}",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return [_parse_component(match.group(1)) for match in pattern.finditer(text)]


def _parse_ics_datetime(value: str, params: dict[str, str] | None = None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    params = params or {}
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", raw):
        return datetime(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?", raw)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    dt = datetime(y, mo, d, h, mi, s)
    if raw.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ics_to_iso(value: str, params: dict[str, str] | None = None) -> str | None:
    dt = _parse_ics_datetime(value, params)
    if not dt:
        raw = (value or "").strip()
        return raw or None
    if params and params.get("VALUE", "").upper() == "DATE":
        return dt.strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{8}", (value or "").strip()):
        return dt.strftime("%Y-%m-%d")
    if dt.tzinfo is timezone.utc or (value or "").endswith("Z"):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _is_all_day(value: str, params: dict[str, str] | None) -> bool:
    params = params or {}
    if params.get("VALUE", "").upper() == "DATE":
        return True
    return bool(re.fullmatch(r"\d{8}", (value or "").strip()))


def _parse_rrule(text: str) -> dict[str, Any]:
    rule: dict[str, Any] = {"FREQ": "", "INTERVAL": 1, "COUNT": None, "UNTIL": None, "BYDAY": []}
    for part in (text or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.upper()
        value = value.strip()
        if key == "FREQ":
            rule["FREQ"] = value.upper()
        elif key == "INTERVAL":
            try:
                rule["INTERVAL"] = max(1, int(value))
            except ValueError:
                rule["INTERVAL"] = 1
        elif key == "COUNT":
            try:
                rule["COUNT"] = max(1, int(value))
            except ValueError:
                rule["COUNT"] = None
        elif key == "UNTIL":
            rule["UNTIL"] = _parse_ics_datetime(value, {"VALUE": "DATE"} if len(value) == 8 else {})
        elif key == "BYDAY":
            days = []
            for token in value.split(","):
                token = token.strip().upper()
                # strip leading ordinal like 1SU / -1MO → SU / MO
                token = re.sub(r"^[+-]?\d+", "", token)
                if token in _ICAL_WEEKDAY:
                    days.append(_ICAL_WEEKDAY[token])
            rule["BYDAY"] = days
    return rule


def _exdates(component: dict[str, Any]) -> set[date]:
    out: set[date] = set()
    params_map = component.get("params") or {}
    for raw in (component.get("multi") or {}).get("EXDATE", []):
        # EXDATE can be comma-separated
        for piece in raw.split(","):
            dt = _parse_ics_datetime(piece.strip(), params_map.get("EXDATE"))
            if dt:
                out.add(dt.date())
    return out


def _expansion_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now()
    start = (now - timedelta(days=_EXPAND_PAST_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=_EXPAND_FUTURE_DAYS)).replace(hour=23, minute=59, second=59, microsecond=0)
    return start, end


def _iter_rrule_dates(
    dtstart: datetime,
    rrule_text: str,
    window_start: datetime,
    window_end: datetime,
    exdates: set[date] | None = None,
) -> list[datetime]:
    """Expand DAILY / WEEKLY RRULEs (Apple Calendar common cases) into window."""
    rule = _parse_rrule(rrule_text)
    freq = rule["FREQ"]
    if freq not in {"DAILY", "WEEKLY"}:
        if window_start <= dtstart <= window_end and (not exdates or dtstart.date() not in exdates):
            return [dtstart]
        return []

    interval = int(rule["INTERVAL"] or 1)
    count = rule["COUNT"]
    until = rule["UNTIL"]
    byday = rule["BYDAY"]
    exdates = exdates or set()

    def _allowed(occ: datetime) -> bool:
        if occ < dtstart:
            return False
        if until and occ.date() > until.date():
            return False
        if occ < window_start or occ > window_end:
            return False
        if occ.date() in exdates:
            return False
        return True

    # Generate from dtstart forward with a hard safety cap, then filter to window.
    occurrences: list[datetime] = []
    max_emit = count if count is not None else 400

    if freq == "DAILY":
        cursor = dtstart
        emitted = 0
        while emitted < max_emit and cursor <= window_end + timedelta(days=interval):
            if until and cursor.date() > until.date():
                break
            if _allowed(cursor):
                occurrences.append(cursor)
            emitted += 1
            cursor += timedelta(days=interval)
            # Skip ahead into window if still before it
            if cursor < window_start:
                skip = ((window_start.date() - cursor.date()).days // interval) * interval
                if skip > 0:
                    # count those skipped toward COUNT
                    steps = skip // interval
                    emitted += steps
                    cursor += timedelta(days=skip)
        return occurrences

    # WEEKLY — Monday-based weeks (Python weekday)
    weekdays = sorted(byday) if byday else [dtstart.weekday()]
    week0 = dtstart.date() - timedelta(days=dtstart.weekday())
    emitted = 0
    week_i = 0
    safety = 0
    while emitted < max_emit and safety < 520:
        safety += 1
        if week_i % interval != 0:
            week_i += 1
            continue
        week_start = week0 + timedelta(weeks=week_i)
        if until and week_start > until.date() + timedelta(days=7):
            break
        if week_start > window_end.date() + timedelta(days=7):
            break
        for wd in weekdays:
            if emitted >= max_emit:
                break
            occ_date = week_start + timedelta(days=wd)
            occ = datetime(
                occ_date.year,
                occ_date.month,
                occ_date.day,
                dtstart.hour,
                dtstart.minute,
                dtstart.second,
                tzinfo=dtstart.tzinfo,
            )
            if occ < dtstart:
                continue
            if until and occ.date() > until.date():
                continue
            # COUNT counts all series instances, including those before the window
            emitted += 1
            if occ.date() in exdates:
                continue
            if window_start <= occ <= window_end:
                occurrences.append(occ)
        week_i += 1
        # Fast-forward weeks before window
        win_week = window_start.date() - timedelta(days=window_start.weekday())
        if week0 + timedelta(weeks=week_i) < win_week:
            target = ((win_week - week0).days // 7)
            target = target - (target % interval)
            if target > week_i:
                # Don't skip COUNT accounting for WEEKLY with BYDAY — stay sequential
                pass
    occurrences.sort()
    return occurrences


def _occurrence_iso(master_start: datetime, master_end: datetime | None, occ: datetime, all_day: bool) -> tuple[str, str]:
    duration = (master_end - master_start) if master_end else timedelta(hours=1 if not all_day else 24)
    if all_day and duration.total_seconds() <= 0:
        duration = timedelta(days=1)
    occ_end = occ + duration
    if all_day:
        return occ.strftime("%Y-%m-%d"), occ_end.strftime("%Y-%m-%d")
    fmt = "%Y-%m-%dT%H:%M:%S"
    if occ.tzinfo is timezone.utc:
        return occ.strftime(fmt + "Z"), occ_end.strftime(fmt + "Z")
    return occ.strftime(fmt), occ_end.strftime(fmt)


def _events_from_ics(ics_text: str, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    window_start, window_end = _expansion_window()
    for component in _iter_components(ics_text, "VEVENT"):
        props = component["props"]
        params = component["params"]
        title = props.get("SUMMARY") or "Event"
        raw_start = props.get("DTSTART", "")
        start_dt = _parse_ics_datetime(raw_start, params.get("DTSTART"))
        if not start_dt:
            continue
        end_dt = _parse_ics_datetime(props.get("DTEND", ""), params.get("DTEND")) or (
            start_dt + timedelta(days=1 if _is_all_day(raw_start, params.get("DTSTART")) else 0)
        )
        all_day = _is_all_day(raw_start, params.get("DTSTART"))
        uid = props.get("UID") or f"{title}-{raw_start}"
        rrule = props.get("RRULE", "")
        exdates = _exdates(component)
        location = props.get("LOCATION") or None
        notes = props.get("DESCRIPTION") or None

        if rrule:
            occs = _iter_rrule_dates(start_dt, rrule, window_start, window_end, exdates)
        else:
            occs = [start_dt] if window_start <= start_dt <= window_end or start_dt.date() <= window_end.date() else []
            # Always keep non-recurring even if slightly outside past window but still future relative
            if not occs and start_dt <= window_end and (end_dt or start_dt) >= window_start - timedelta(days=1):
                occs = [start_dt]

        for occ in occs:
            start_iso, end_iso = _occurrence_iso(start_dt, end_dt, occ, all_day)
            occ_id = f"caldav:{uid}" if not rrule else f"caldav:{uid}:{occ.strftime('%Y%m%d')}"
            events.append(
                {
                    "id": occ_id,
                    "title": title,
                    "start": start_iso,
                    "end": end_iso,
                    "allDay": all_day,
                    "location": location,
                    "notes": notes,
                    "source": source,
                    "recurring": bool(rrule),
                }
            )
    return events


def _chores_from_ics(ics_text: str, source: str) -> list[dict[str, Any]]:
    chores: list[dict[str, Any]] = []
    # Same horizon as events so reminders fill the month grid when merged into Family.
    window_start, window_end = _expansion_window()
    for component in _iter_components(ics_text, "VTODO"):
        props = component["props"]
        params = component["params"]
        title = props.get("SUMMARY") or "Chore"
        status = (props.get("STATUS") or "").upper()
        done = status == "COMPLETED" or bool(props.get("COMPLETED"))
        raw_due = props.get("DUE") or props.get("DTSTART") or ""
        due_params = params.get("DUE") or params.get("DTSTART") or {}
        due_dt = _parse_ics_datetime(raw_due, due_params)
        uid = props.get("UID") or f"{title}-{raw_due}"
        rrule = props.get("RRULE", "")
        notes = props.get("DESCRIPTION") or None
        assignee = props.get("X-APPLE-ASSIGNEE") or props.get("ATTENDEE") or None
        exdates = _exdates(component)

        if rrule and due_dt and not done:
            occs = _iter_rrule_dates(due_dt, rrule, window_start, window_end, exdates)
            for occ in occs:
                due_iso = (
                    occ.strftime("%Y-%m-%d")
                    if _is_all_day(raw_due, due_params)
                    else occ.strftime("%Y-%m-%dT%H:%M:%S")
                )
                chores.append(
                    {
                        "id": f"caldav:{uid}:{occ.strftime('%Y%m%d')}",
                        "title": title,
                        "assignee": assignee,
                        "due": due_iso,
                        "notes": notes,
                        "done": False,
                        "source": source,
                        "recurring": True,
                    }
                )
        else:
            due_iso = _ics_to_iso(raw_due, due_params) if raw_due else None
            chores.append(
                {
                    "id": f"caldav:{uid}",
                    "title": title,
                    "assignee": assignee,
                    "due": due_iso,
                    "notes": notes,
                    "done": done,
                    "source": source,
                    "recurring": bool(rrule),
                }
            )

    # Fallback: treat VEVENT in chores calendar as open chores
    if not chores:
        for event in _events_from_ics(ics_text, source):
            chores.append(
                {
                    "id": event["id"],
                    "title": event["title"],
                    "assignee": None,
                    "due": (event.get("start") or "")[:10] or None,
                    "notes": event.get("notes"),
                    "done": False,
                    "source": source,
                    "recurring": bool(event.get("recurring")),
                }
            )
    return chores


def fetch_board() -> dict[str, Any]:
    if not caldav_configured():
        return {"ok": False, "enabled": False, "events": [], "chores": [], "error": "CalDAV not configured"}

    events: list[dict[str, Any]] = []
    chores: list[dict[str, Any]] = []
    errors: list[str] = []

    if CALDAV_EVENTS_CALENDAR:
        try:
            xml = _report_calendar(CALDAV_EVENTS_CALENDAR)
            for blob in _extract_calendar_data_blobs(xml):
                events.extend(_events_from_ics(blob, "caldav-events"))
        except Exception as exc:
            errors.append(f"events: {exc}")

    if CALDAV_CHORES_CALENDAR:
        try:
            xml = _report_calendar(CALDAV_CHORES_CALENDAR)
            for blob in _extract_calendar_data_blobs(xml):
                chores.extend(_chores_from_ics(blob, "caldav-chores"))
        except Exception as exc:
            errors.append(f"chores: {exc}")

    # de-dupe by id
    def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        out = []
        for row in rows:
            key = row.get("id")
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    return {
        "ok": not errors,
        "enabled": True,
        "events": dedupe(events),
        "chores": dedupe(chores),
        "error": "; ".join(errors) if errors else None,
        "accountHint": {
            "server": CALDAV_URL,
            "user": CALDAV_USER,
            "eventsCalendar": CALDAV_EVENTS_CALENDAR,
            "choresCalendar": CALDAV_CHORES_CALENDAR,
        },
    }
