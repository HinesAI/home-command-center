import json
import os
import ssl
import time
import http.client
import urllib.error
import urllib.request


HA_URL = os.environ.get("HCC_HA_URL", "http://192.168.1.20:8123").rstrip("/")
HA_TOKEN = os.environ.get("HCC_HA_TOKEN", "").strip()
HA_DOOR_DEVICE_CLASSES = {
    value.strip().lower()
    for value in os.environ.get("HCC_HA_DOOR_DEVICE_CLASSES", "door,opening,garage_door").split(",")
    if value.strip()
}
HA_DOOR_ENTITY_SUFFIX_EXCLUDE = (
    "_battery",
    "_firmware",
    "_identify",
    "_opening",
)
HA_CLIMATE_ENTITIES = [
    value.strip()
    for value in os.environ.get("HCC_HA_CLIMATE_ENTITIES", "").split(",")
    if value.strip()
]
CLIMATE_REFRESH_SECONDS = int(os.environ.get("HCC_CLIMATE_REFRESH_SECONDS", "30"))
FRIGATE_URL = os.environ.get("HCC_FRIGATE_URL", "http://192.168.1.30:5000").rstrip("/")
INTEGRATION_TIMEOUT = float(os.environ.get("HCC_INTEGRATION_TIMEOUT", "5"))
FRIGATE_CAMERA_PATH_PREFIX = "/api/v1/integrations/frigate/camera/"

WEATHER_LAT = float(os.environ.get("HCC_WEATHER_LAT", "33.9090855"))
WEATHER_LON = float(os.environ.get("HCC_WEATHER_LON", "-87.3901102"))
WEATHER_LABEL = os.environ.get("HCC_WEATHER_LABEL", "919 Old Zion Rd · Nauvoo, AL").strip() or "919 Old Zion Rd · Nauvoo, AL"
WEATHER_TIMEZONE = os.environ.get("HCC_WEATHER_TIMEZONE", "America/Chicago").strip() or "America/Chicago"
WEATHER_CACHE_SECONDS = int(os.environ.get("HCC_WEATHER_CACHE_SECONDS", "900"))
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

UNIFI_URL = os.environ.get("HCC_UNIFI_URL", "https://192.168.1.1").rstrip("/")
UNIFI_API_KEY = os.environ.get("HCC_UNIFI_API_KEY", "").strip()
UNIFI_SITE = os.environ.get("HCC_UNIFI_SITE", "default").strip() or "default"
UNIFI_VERIFY_SSL = os.environ.get("HCC_UNIFI_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
NETWORK_CACHE_SECONDS = int(os.environ.get("HCC_NETWORK_CACHE_SECONDS", "60"))

_weather_cache = {"fetched_at": 0.0, "payload": None}
_network_cache = {"fetched_at": 0.0, "payload": None}
_unifi_ssl_context = None

GATEWAY_DEVICE_TYPES = {"udm", "ugw", "uxg", "uos", "ugw3", "ugw4", "ugwHD", "ugwXG"}

WEATHER_CODE_META = {
    0: ("Clear sky", "clear"),
    1: ("Mainly clear", "clear"),
    2: ("Partly cloudy", "partly-cloudy"),
    3: ("Overcast", "overcast"),
    45: ("Fog", "fog"),
    48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"),
    57: ("Heavy freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Heavy freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"),
    99: ("Heavy thunderstorm with hail", "storm"),
}


def _fetch_text(url, timeout=INTEGRATION_TIMEOUT, headers=None):
    started = time.time()
    request = urllib.request.Request(url, headers={"Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace").strip()
        latency_ms = round((time.time() - started) * 1000, 1)
        return body, latency_ms, response.status


def _fetch_json(url, timeout=INTEGRATION_TIMEOUT, headers=None):
    started = time.time()
    request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        latency_ms = round((time.time() - started) * 1000, 1)
        return json.loads(body) if body else {}, latency_ms, response.status


def _unifi_ssl_context():
    global _unifi_ssl_context
    if _unifi_ssl_context is None:
        _unifi_ssl_context = ssl.create_default_context()
        if not UNIFI_VERIFY_SSL:
            _unifi_ssl_context.check_hostname = False
            _unifi_ssl_context.verify_mode = ssl.CERT_NONE
    return _unifi_ssl_context


def _unifi_headers():
    headers = {"Accept": "application/json"}
    if UNIFI_API_KEY:
        headers["X-API-Key"] = UNIFI_API_KEY
    return headers


def _fetch_unifi_json(path, method="GET", body=None, timeout=INTEGRATION_TIMEOUT):
    started = time.time()
    url = f"{UNIFI_URL}{path}"
    data = None
    headers = _unifi_headers()
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout, context=_unifi_ssl_context()) as response:
        raw = response.read().decode("utf-8", errors="replace")
        latency_ms = round((time.time() - started) * 1000, 1)
        payload = json.loads(raw) if raw else {}
        return payload, latency_ms, response.status


def _ms_to_iso(value):
    if value in (None, "", 0):
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts > 1_000_000_000_000:
        ts /= 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _pick_gateway_device(devices):
    for device in devices or []:
        device_type = str(device.get("type") or "").lower()
        model = str(device.get("model") or "")
        if device_type in GATEWAY_DEVICE_TYPES or "udm" in model.lower() or "dream" in model.lower():
            return device
    for device in devices or []:
        if device.get("uplink"):
            return device
    return None


def _speedtest_from_uplink(uplink):
    if not isinstance(uplink, dict):
        return None
    download = uplink.get("xput_down")
    if download is None:
        download = uplink.get("xput_download")
    upload = uplink.get("xput_up")
    if upload is None:
        upload = uplink.get("xput_upload")
    latency = uplink.get("speedtest_ping")
    if latency is None:
        latency = uplink.get("latency")
    tested_at = uplink.get("speedtest_lastsuccess")
    if tested_at in (None, "", 0):
        tested_at = uplink.get("speedtest_last_run")
    if download in (None, "", 0) and upload in (None, "", 0) and latency in (None, "", 0):
        return None
    return {
        "downloadMbps": _round_value(download),
        "uploadMbps": _round_value(upload),
        "latencyMs": _round_value(latency, 0),
        "testedAt": _ms_to_iso(tested_at),
        "status": uplink.get("speedtest_status"),
        "source": "uplink",
    }


def _latest_archive_speedtest():
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (30 * 24 * 60 * 60 * 1000)
    payload, _latency, _status = _fetch_unifi_json(
        f"/proxy/network/api/s/{UNIFI_SITE}/stat/report/archive.speedtest",
        method="POST",
        body={
            "attrs": ["xput_download", "xput_upload", "latency", "time"],
            "start": start_ms,
            "end": end_ms,
        },
    )
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        return None
    latest = max(rows, key=lambda row: float(row.get("time") or 0))
    return {
        "downloadMbps": _round_value(latest.get("xput_download")),
        "uploadMbps": _round_value(latest.get("xput_upload")),
        "latencyMs": _round_value(latest.get("latency"), 0),
        "testedAt": _ms_to_iso(latest.get("time")),
        "status": "archive",
        "source": "archive",
    }


def network_integrations(refresh_seconds=None):
    refresh_seconds = refresh_seconds or NETWORK_CACHE_SECONDS
    now = time.time()
    if _network_cache["payload"] and (now - _network_cache["fetched_at"]) < refresh_seconds:
        cached = dict(_network_cache["payload"])
        cached["cached"] = True
        return cached

    base = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refreshSeconds": refresh_seconds,
        "provider": "unifi",
        "gatewayUrl": UNIFI_URL,
        "configured": bool(UNIFI_API_KEY),
        "online": False,
        "latencyMs": None,
        "gateway": None,
        "speedtest": None,
        "error": None,
        "cached": False,
    }

    if not UNIFI_API_KEY:
        base["error"] = "UniFi API key not configured (set HCC_UNIFI_API_KEY in deploy/.env)"
        _network_cache["fetched_at"] = now
        _network_cache["payload"] = base
        return base

    try:
        payload, latency_ms, _status = _fetch_unifi_json(
            f"/proxy/network/api/s/{UNIFI_SITE}/stat/device",
        )
        devices = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(devices, list):
            raise ValueError("unexpected UniFi device response")
        gateway = _pick_gateway_device(devices)
        if not gateway:
            raise ValueError("no UniFi gateway device found")

        uplink = gateway.get("uplink") or {}
        speedtest = _speedtest_from_uplink(uplink)
        if speedtest is None:
            speedtest = _latest_archive_speedtest()

        base.update(
            {
                "online": True,
                "latencyMs": latency_ms,
                "gateway": {
                    "name": gateway.get("name") or gateway.get("model") or "Gateway",
                    "model": gateway.get("model"),
                    "mac": gateway.get("mac"),
                    "version": gateway.get("version"),
                    "wanIp": uplink.get("ip"),
                    "wanUp": bool(uplink.get("up", True)),
                },
                "speedtest": speedtest,
                "error": None if speedtest else "No speedtest results returned from UniFi yet",
            }
        )
        _network_cache["fetched_at"] = now
        _network_cache["payload"] = base
        return base
    except Exception as exc:
        if _network_cache["payload"]:
            stale = dict(_network_cache["payload"])
            stale["cached"] = True
            stale["stale"] = True
            stale["error"] = str(exc)
            return stale
        base["error"] = str(exc)
        _network_cache["fetched_at"] = now
        _network_cache["payload"] = base
        return base


def _probe_url(url, timeout=INTEGRATION_TIMEOUT, headers=None):
    started = time.time()
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        latency_ms = round((time.time() - started) * 1000, 1)
        return True, latency_ms, response.status, ""


def _ha_headers():
    if not HA_TOKEN:
        return {}
    return {"Authorization": f"Bearer {HA_TOKEN}"}


def _format_ha_service_error(exc):
    message = str(exc).lower()
    if any(
        token in message
        for token in ("remote end closed", "connection reset", "empty reply", "broken pipe")
    ):
        return (
            "Home Assistant closed the connection while sending the climate command. "
            "The Sensi integration in HA likely crashed — reload it under Settings → "
            "Devices & Services → Sensi, update to iprak/sensi v2.1.3+, and check HA logs."
        )
    return str(exc)


def _post_ha_service(domain, service, data):
    if not HA_TOKEN:
        raise RuntimeError("Home Assistant token not configured")
    url = f"{HA_URL}/api/services/{domain}/{service}"
    payload = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", **_ha_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=INTEGRATION_TIMEOUT) as response:
            return response.status
    except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError) as exc:
        raise RuntimeError(_format_ha_service_error(exc)) from exc


def _refresh_ha_climate_entities(entity_ids):
    if not HA_TOKEN:
        return
    for entity_id in entity_ids:
        try:
            _post_ha_service("homeassistant", "update_entity", {"entity_id": entity_id})
        except Exception:
            pass


def _round_temp(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _climate_entity_prefix(entity_id):
    return str(entity_id or "").split(".", 1)[-1]


def _related_sensor_state(states_by_id, climate_entity_id, suffix):
    prefix = _climate_entity_prefix(climate_entity_id)
    entry = states_by_id.get(f"sensor.{prefix}_{suffix}")
    if not entry:
        return None
    state = str(entry.get("state") or "")
    if state in {"unavailable", "unknown", "none", ""}:
        return None
    try:
        return int(round(float(state)))
    except (TypeError, ValueError):
        return state


def _climate_online(states_by_id, climate_entity_id, state):
    prefix = _climate_entity_prefix(climate_entity_id)
    online_entry = states_by_id.get(f"binary_sensor.{prefix}_online")
    if online_entry:
        return str(online_entry.get("state") or "").lower() in {"on", "true", "1"}
    return str(state or "").lower() not in {"unavailable", "unknown", "none"}


def _format_hvac_mode(mode):
    labels = {
        "off": "Off",
        "heat": "Heat",
        "cool": "Cool",
        "auto": "Auto",
        "heat_cool": "Auto",
    }
    return labels.get(str(mode or "").lower(), str(mode or "Unknown").title())


def _format_hvac_action(action):
    labels = {
        "idle": "Idle",
        "heating": "Heating",
        "cooling": "Cooling",
        "off": "Off",
        "drying": "Drying",
        "fan": "Fan",
    }
    return labels.get(str(action or "").lower(), str(action or "—").title())


def _parse_climate_entity(entry, states_by_id):
    entity_id = str(entry.get("entity_id") or "")
    attrs = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
    state = str(entry.get("state") or "")
    hvac_mode = str(attrs.get("hvac_mode") or state or "unknown").lower()
    target = _round_temp(attrs.get("temperature"))
    if target is None and hvac_mode == "auto":
        target = _round_temp(attrs.get("target_temp_low"))
    return {
        "entityId": entity_id,
        "name": str(attrs.get("friendly_name") or entity_id),
        "online": _climate_online(states_by_id, entity_id, state),
        "hvacMode": hvac_mode,
        "hvacModes": [str(mode).lower() for mode in (attrs.get("hvac_modes") or []) if str(mode)],
        "hvacAction": str(attrs.get("hvac_action") or "unknown").lower(),
        "hvacActionLabel": _format_hvac_action(attrs.get("hvac_action")),
        "hvacModeLabel": _format_hvac_mode(hvac_mode),
        "currentTemperatureF": _round_temp(attrs.get("current_temperature")),
        "targetTemperatureF": target,
        "targetTempHighF": _round_temp(attrs.get("target_temp_high")),
        "targetTempLowF": _round_temp(attrs.get("target_temp_low")),
        "fanMode": str(attrs.get("fan_mode") or "").lower() or None,
        "fanModes": [str(mode) for mode in (attrs.get("fan_modes") or []) if str(mode)],
        "humidity": _related_sensor_state(states_by_id, entity_id, "humidity")
        or _round_temp(attrs.get("current_humidity")),
        "minTempF": _round_temp(attrs.get("min_temp")),
        "maxTempF": _round_temp(attrs.get("max_temp")),
        "lastChanged": str(entry.get("last_changed") or ""),
        "entityUrl": f"{HA_URL}/lovelace/0?entity_id={entity_id}",
    }


def _fetch_home_assistant_climate():
    if not HA_TOKEN:
        return {
            "configured": False,
            "haOnline": False,
            "thermostats": [],
            "error": "Home Assistant token not configured",
        }

    try:
        states, _latency, status_code = _fetch_json(f"{HA_URL}/api/states", headers=_ha_headers())
        ha_online = status_code < 500
        allowed = set(HA_CLIMATE_ENTITIES)
        climate_entity_ids = []
        for entry in states if isinstance(states, list) else []:
            if not isinstance(entry, dict):
                continue
            entity_id = str(entry.get("entity_id") or "")
            if not entity_id.startswith("climate."):
                continue
            if allowed and entity_id not in allowed:
                continue
            climate_entity_ids.append(entity_id)
        if climate_entity_ids:
            _refresh_ha_climate_entities(climate_entity_ids)
            states, _latency, status_code = _fetch_json(f"{HA_URL}/api/states", headers=_ha_headers())
            ha_online = status_code < 500
        states_by_id = {
            str(entry.get("entity_id")): entry
            for entry in (states if isinstance(states, list) else [])
            if isinstance(entry, dict) and entry.get("entity_id")
        }
        thermostats = []
        for entry in states if isinstance(states, list) else []:
            if not isinstance(entry, dict):
                continue
            entity_id = str(entry.get("entity_id") or "")
            if not entity_id.startswith("climate."):
                continue
            if allowed and entity_id not in allowed:
                continue
            thermostats.append(_parse_climate_entity(entry, states_by_id))
        thermostats.sort(key=lambda row: row["name"].lower())
        return {
            "configured": True,
            "haOnline": ha_online,
            "thermostats": thermostats,
            "error": None,
        }
    except Exception as exc:
        return {
            "configured": True,
            "haOnline": False,
            "thermostats": [],
            "error": str(exc),
        }


def climate_integrations(refresh_seconds=None):
    refresh_seconds = refresh_seconds or CLIMATE_REFRESH_SECONDS
    data = _fetch_home_assistant_climate()
    thermostats = data.get("thermostats") or []
    online_count = sum(1 for row in thermostats if row.get("online"))
    active_count = sum(
        1
        for row in thermostats
        if row.get("online") and str(row.get("hvacAction") or "").lower() in {"heating", "cooling"}
    )
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refreshSeconds": refresh_seconds,
        "haUrl": HA_URL,
        "configured": data.get("configured", False),
        "haOnline": data.get("haOnline", False),
        "thermostats": thermostats,
        "totals": {
            "thermostatCount": len(thermostats),
            "onlineCount": online_count,
            "activeCount": active_count,
        },
        "error": data.get("error"),
    }


def set_climate_control(entity_id, hvac_mode=None, temperature=None, fan_mode=None, target_temp_high=None, target_temp_low=None):
    entity_id = str(entity_id or "").strip()
    if not entity_id or not entity_id.startswith("climate."):
        raise ValueError("invalid climate entity id")
    if HA_CLIMATE_ENTITIES and entity_id not in HA_CLIMATE_ENTITIES:
        raise ValueError("climate entity not allowlisted")

    if hvac_mode is not None:
        _post_ha_service(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": str(hvac_mode).lower()},
        )

    if temperature is not None:
        _post_ha_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": float(temperature)},
        )

    if target_temp_high is not None or target_temp_low is not None:
        payload = {"entity_id": entity_id}
        if target_temp_high is not None:
            payload["target_temp_high"] = float(target_temp_high)
        if target_temp_low is not None:
            payload["target_temp_low"] = float(target_temp_low)
        _post_ha_service("climate", "set_temperature", payload)

    if fan_mode is not None:
        _post_ha_service(
            "climate",
            "set_fan_mode",
            {"entity_id": entity_id, "fan_mode": str(fan_mode)},
        )

    if all(value is None for value in (hvac_mode, temperature, fan_mode, target_temp_high, target_temp_low)):
        raise ValueError("no climate changes requested")

    return climate_integrations()


def _is_door_sensor(entity_id, attrs):
    domain = entity_id.split(".")[0]
    if domain != "binary_sensor":
        return False
    device_class = str(attrs.get("device_class") or "").lower()
    if device_class not in HA_DOOR_DEVICE_CLASSES:
        return False
    lowered = entity_id.lower()
    return not any(lowered.endswith(suffix) for suffix in HA_DOOR_ENTITY_SUFFIX_EXCLUDE)


def _format_door_state(state):
    value = str(state or "").lower()
    if value in {"on", "open", "opened"}:
        return "Open"
    if value in {"off", "closed", "close"}:
        return "Closed"
    if value in {"unavailable", "unknown", "none"}:
        return "Unavailable"
    return str(state or "Unknown")


def _door_state_class(state):
    label = _format_door_state(state)
    if label == "Open":
        return "status-stopped"
    if label == "Closed":
        return "status-running"
    return "status-starting"


def _fetch_home_assistant_sensors():
    if not HA_TOKEN:
        return {
            "configured": False,
            "sensorCount": 0,
            "onlineCount": 0,
            "offlineCount": 0,
            "sensors": [],
            "error": "Home Assistant token not configured",
            "filter": "door",
        }

    try:
        states, _latency, _status = _fetch_json(f"{HA_URL}/api/states", headers=_ha_headers())
        sensors = []
        if isinstance(states, list):
            for entry in states:
                if not isinstance(entry, dict):
                    continue
                entity_id = str(entry.get("entity_id") or "")
                attrs = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
                if not _is_door_sensor(entity_id, attrs):
                    continue
                state = entry.get("state")
                door_state = _format_door_state(state)
                sensors.append(
                    {
                        "entityId": entity_id,
                        "name": str(attrs.get("friendly_name") or entity_id),
                        "state": door_state,
                        "rawState": str(state if state is not None else "unknown"),
                        "deviceClass": str(attrs.get("device_class") or ""),
                        "lastChanged": str(entry.get("last_changed") or ""),
                        "status": "offline" if door_state == "Unavailable" else "online",
                        "stateClass": _door_state_class(state),
                    }
                )
        sensors.sort(key=lambda row: row["name"].lower())
        online_count = sum(1 for row in sensors if row["status"] == "online")
        return {
            "configured": True,
            "sensorCount": len(sensors),
            "onlineCount": online_count,
            "offlineCount": len(sensors) - online_count,
            "sensors": sensors,
            "filter": "door",
            "error": None,
        }
    except Exception as exc:
        return {
            "configured": True,
            "sensorCount": 0,
            "onlineCount": 0,
            "offlineCount": 0,
            "sensors": [],
            "filter": "door",
            "error": str(exc),
        }


def _probe_home_assistant():
    item = {
        "id": "home-assistant",
        "name": "Home Assistant",
        "kind": "home-automation",
        "host": HA_URL.replace("http://", "").replace("https://", ""),
        "url": HA_URL,
        "dashboardUrl": HA_URL,
        "online": False,
        "latencyMs": None,
        "statusCode": None,
        "error": None,
        "details": {
            "sensorsConfigured": bool(HA_TOKEN),
            "sensorFilter": "door",
            "sensorCount": 0,
            "sensorOnlineCount": 0,
            "sensorOfflineCount": 0,
            "sensors": [],
        },
    }
    headers = _ha_headers()
    try:
        if HA_TOKEN:
            _payload, latency_ms, status_code = _fetch_json(f"{HA_URL}/api/", headers=headers)
            item["online"] = status_code < 500
            item["latencyMs"] = latency_ms
            item["statusCode"] = status_code
        else:
            online, latency_ms, status_code, _message = _probe_url(HA_URL)
            item["online"] = online and status_code < 500
            item["latencyMs"] = latency_ms
            item["statusCode"] = status_code
    except urllib.error.HTTPError as exc:
        item["online"] = exc.code < 500
        item["statusCode"] = exc.code
        item["latencyMs"] = round(INTEGRATION_TIMEOUT * 1000, 1)
        item["error"] = str(exc.reason or exc)
    except Exception as exc:
        item["error"] = str(exc)

    sensor_data = _fetch_home_assistant_sensors()
    item["details"]["sensorsConfigured"] = sensor_data["configured"]
    item["details"]["sensorFilter"] = sensor_data.get("filter", "door")
    item["details"]["sensorCount"] = sensor_data["sensorCount"]
    item["details"]["sensorOnlineCount"] = sensor_data["onlineCount"]
    item["details"]["sensorOfflineCount"] = sensor_data["offlineCount"]
    item["details"]["sensors"] = sensor_data["sensors"]
    if sensor_data["error"] and not item["error"]:
        item["error"] = sensor_data["error"]
    if sensor_data["configured"] and sensor_data["sensorCount"] > 0 and item["online"]:
        item["online"] = True
    return item


def frigate_camera_preview_path(camera_name):
    return f"{FRIGATE_CAMERA_PATH_PREFIX}{camera_name}/latest.jpg"


def fetch_frigate_camera_latest(camera_name):
    safe_name = str(camera_name or "").strip()
    if not safe_name or "/" in safe_name or ".." in safe_name:
        raise ValueError("invalid camera name")
    url = f"{FRIGATE_URL}/api/{safe_name}/latest.jpg"
    request = urllib.request.Request(url, headers={"Accept": "image/jpeg"})
    with urllib.request.urlopen(request, timeout=INTEGRATION_TIMEOUT) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "image/jpeg")
    if not body:
        raise RuntimeError("empty camera image")
    return body, content_type


def _probe_frigate():
    item = {
        "id": "frigate",
        "name": "Frigate NVR",
        "kind": "nvr",
        "host": FRIGATE_URL.replace("http://", "").replace("https://", ""),
        "url": FRIGATE_URL,
        "dashboardUrl": FRIGATE_URL,
        "online": False,
        "latencyMs": None,
        "statusCode": None,
        "error": None,
        "details": {
            "version": None,
            "cameraCount": 0,
            "detectionEnabledCount": 0,
            "cameras": [],
        },
    }
    try:
        _online, latency_ms, status_code, _message = _probe_url(FRIGATE_URL)
        item["latencyMs"] = latency_ms
        item["statusCode"] = status_code
        item["online"] = status_code < 500
    except Exception as exc:
        item["error"] = str(exc)
        return item

    try:
        version_text, _latency, _status = _fetch_text(f"{FRIGATE_URL}/api/version")
        if version_text:
            item["details"]["version"] = version_text
    except Exception:
        pass

    try:
        stats, _latency, _status = _fetch_json(f"{FRIGATE_URL}/api/stats")
        cameras = []
        if isinstance(stats, dict):
            for name, camera in stats.get("cameras", {}).items():
                if not isinstance(camera, dict):
                    continue
                camera_fps = camera.get("camera_fps") or 0
                cameras.append(
                    {
                        "name": name,
                        "online": float(camera_fps) > 0,
                        "cameraFps": camera.get("camera_fps"),
                        "detectionFps": camera.get("detection_fps"),
                        "detectionEnabled": bool(camera.get("detection_enabled")),
                        "previewUrl": frigate_camera_preview_path(name),
                        "latestImageUrl": f"{FRIGATE_URL}/api/{name}/latest.jpg",
                        "livePageUrl": f"{FRIGATE_URL}/live/{name}",
                    }
                )
        cameras.sort(key=lambda row: row["name"].lower())
        item["details"]["cameras"] = cameras
        item["details"]["cameraCount"] = len(cameras)
        item["details"]["onlineCameraCount"] = sum(1 for row in cameras if row["online"])
        item["details"]["detectionEnabledCount"] = sum(1 for row in cameras if row["detectionEnabled"])
        item["online"] = True
    except Exception as exc:
        item["error"] = str(exc)
        item["online"] = False

    return item


def security_integrations(refresh_seconds=60):
    services = [_probe_home_assistant(), _probe_frigate()]
    online_count = sum(1 for service in services if service["online"])
    camera_count = 0
    sensor_count = 0
    for service in services:
        if service["id"] == "frigate":
            camera_count = service.get("details", {}).get("cameraCount") or 0
        if service["id"] == "home-assistant":
            sensor_count = service.get("details", {}).get("sensorCount") or 0
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refreshSeconds": refresh_seconds,
        "totals": {
            "serviceCount": len(services),
            "onlineCount": online_count,
            "offlineCount": len(services) - online_count,
            "cameraCount": camera_count,
            "sensorCount": sensor_count,
        },
        "services": services,
    }


def _weather_code_meta(code):
    return WEATHER_CODE_META.get(int(code or 0), ("Unknown", "overcast"))


def _wind_direction_label(degrees):
    if degrees is None:
        return "-"
    try:
        value = float(degrees)
    except (TypeError, ValueError):
        return "-"
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((value + 11.25) / 22.5) % 16
    return directions[index]


def _format_local_time(iso_value):
    if not iso_value:
        return "-"
    try:
        if "T" in iso_value:
            return iso_value.split("T", 1)[1][:5]
        return iso_value
    except Exception:
        return "-"


def _today_date_in_weather_tz():
    try:
        import datetime
        from zoneinfo import ZoneInfo

        return datetime.datetime.now(ZoneInfo(WEATHER_TIMEZONE)).date().isoformat()
    except Exception:
        return time.strftime("%Y-%m-%d", time.gmtime())


def _weekday_label(date_value):
    try:
        import datetime

        parsed = datetime.date.fromisoformat(date_value)
        return parsed.strftime("%a")
    except Exception:
        return date_value


def _round_value(value, digits=0):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if digits == 0:
        return int(round(number))
    return round(number, digits)


def _fetch_open_meteo():
    from urllib.parse import urlencode

    params = urlencode(
        {
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "uv_index",
                    "is_day",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "apparent_temperature_max",
                    "apparent_temperature_min",
                    "precipitation_sum",
                    "precipitation_probability_max",
                    "wind_speed_10m_max",
                    "wind_direction_10m_dominant",
                    "uv_index_max",
                    "sunrise",
                    "sunset",
                ]
            ),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": WEATHER_TIMEZONE,
            "forecast_days": "7",
        }
    )
    url = f"{OPEN_METEO_URL}?{params}"
    return _fetch_json(url, timeout=max(INTEGRATION_TIMEOUT, 8.0))


def _parse_weather_payload(raw):
    current = raw.get("current") or {}
    daily = raw.get("daily") or {}
    current_code = current.get("weather_code")
    current_label, current_class = _weather_code_meta(current_code)
    if current.get("is_day") == 0 and current_class == "clear":
        current_class = "night-clear"

    daily_rows = []
    dates = daily.get("time") or []
    today_date = _today_date_in_weather_tz()
    for index, date_value in enumerate(dates[:7]):
        code = (daily.get("weather_code") or [None])[index]
        label, condition_class = _weather_code_meta(code)
        is_today = date_value == today_date
        daily_rows.append(
            {
                "date": date_value,
                "dayLabel": _weekday_label(date_value),
                "isToday": is_today,
                "weatherCode": code,
                "condition": label,
                "conditionClass": condition_class,
                "highF": _round_value((daily.get("temperature_2m_max") or [None])[index]),
                "lowF": _round_value((daily.get("temperature_2m_min") or [None])[index]),
                "feelsLikeHighF": _round_value((daily.get("apparent_temperature_max") or [None])[index]),
                "feelsLikeLowF": _round_value((daily.get("apparent_temperature_min") or [None])[index]),
                "precipIn": _round_value((daily.get("precipitation_sum") or [None])[index], 2),
                "precipProbabilityMax": _round_value((daily.get("precipitation_probability_max") or [None])[index]),
                "windMphMax": _round_value((daily.get("wind_speed_10m_max") or [None])[index]),
                "windDirection": _wind_direction_label((daily.get("wind_direction_10m_dominant") or [None])[index]),
                "uvIndexMax": _round_value((daily.get("uv_index_max") or [None])[index], 1),
                "sunrise": _format_local_time((daily.get("sunrise") or [None])[index]),
                "sunset": _format_local_time((daily.get("sunset") or [None])[index]),
            }
        )

    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refreshSeconds": WEATHER_CACHE_SECONDS,
        "provider": "open-meteo",
        "location": {
            "label": WEATHER_LABEL,
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "timezone": WEATHER_TIMEZONE,
        },
        "current": {
            "temperatureF": _round_value(current.get("temperature_2m")),
            "feelsLikeF": _round_value(current.get("apparent_temperature")),
            "humidity": _round_value(current.get("relative_humidity_2m")),
            "windMph": _round_value(current.get("wind_speed_10m")),
            "windDirection": _wind_direction_label(current.get("wind_direction_10m")),
            "uvIndex": _round_value(current.get("uv_index"), 1),
            "isDay": bool(current.get("is_day")),
            "weatherCode": current_code,
            "condition": current_label,
            "conditionClass": current_class,
        },
        "daily": daily_rows,
    }


def weather_forecast(refresh_seconds=None):
    refresh_seconds = refresh_seconds or WEATHER_CACHE_SECONDS
    now = time.time()
    if _weather_cache["payload"] and (now - _weather_cache["fetched_at"]) < refresh_seconds:
        cached = dict(_weather_cache["payload"])
        cached["cached"] = True
        return cached

    try:
        raw, latency_ms, _status = _fetch_open_meteo()
        payload = _parse_weather_payload(raw)
        payload["latencyMs"] = latency_ms
        payload["cached"] = False
        payload["error"] = None
        _weather_cache["fetched_at"] = now
        _weather_cache["payload"] = payload
        return payload
    except urllib.error.URLError as exc:
        if _weather_cache["payload"]:
            stale = dict(_weather_cache["payload"])
            stale["cached"] = True
            stale["stale"] = True
            stale["error"] = str(exc)
            return stale
        return {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "refreshSeconds": refresh_seconds,
            "provider": "open-meteo",
            "location": {
                "label": WEATHER_LABEL,
                "latitude": WEATHER_LAT,
                "longitude": WEATHER_LON,
                "timezone": WEATHER_TIMEZONE,
            },
            "current": None,
            "daily": [],
            "error": str(exc),
        }
    except Exception as exc:
        if _weather_cache["payload"]:
            stale = dict(_weather_cache["payload"])
            stale["cached"] = True
            stale["stale"] = True
            stale["error"] = str(exc)
            return stale
        return {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "refreshSeconds": refresh_seconds,
            "provider": "open-meteo",
            "location": {
                "label": WEATHER_LABEL,
                "latitude": WEATHER_LAT,
                "longitude": WEATHER_LON,
                "timezone": WEATHER_TIMEZONE,
            },
            "current": None,
            "daily": [],
            "error": str(exc),
        }
