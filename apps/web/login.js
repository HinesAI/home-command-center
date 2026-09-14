const GATE_FLEET = "/api/v1/fleet/overview?physicalOnly=false";
const GATE_VMS = "/api/v1/fleet/vms";
const GATE_CONTAINERS = "/api/v1/fleet/containers";
const GATE_SECURITY = "/api/v1/integrations/security";
const GATE_WEATHER = "/api/v1/integrations/weather";
const GATE_CLIMATE = "/api/v1/integrations/climate";

function paintGateAscii() {
  const wide = document.getElementById("gateAsciiWide");
  const narrow = document.getElementById("gateAsciiNarrow");
  if (wide) wide.textContent = HCC_ASCII_WIDE;
  if (narrow) narrow.textContent = HCC_ASCII_NARROW;
}

function serverRows(fleetPayload) {
  const groups = (fleetPayload && fleetPayload.groups) || {};
  return groups.servers || (fleetPayload.items || []).filter((item) => item.deviceCategory !== "client");
}

function paintGateWeather(payload) {
  if (!payload || (payload.error && !payload.current)) {
    setStatusPill("gateWeatherStatus", "offline", "critical");
    setText("gateWeatherTemp", "--°");
    setText("gateWeatherCondition", payload?.error || "Unavailable");
    setText("gateWeatherMeta", "-");
    return;
  }
  const current = payload.current || {};
  const location = payload.location || {};
  setStatusPill("gateWeatherStatus", "live", "ok");
  setText("gateWeatherTemp", `${current.temperatureF ?? "--"}°`);
  setText("gateWeatherCondition", current.condition || "-");
  setText(
    "gateWeatherMeta",
    [location.label || "", current.humidity != null ? `${current.humidity}% humidity` : ""]
      .filter(Boolean)
      .join(" · ") || "-",
  );
}

function paintGateClimate(payload) {
  const thermostat = (payload?.thermostats || [])[0];
  if (!payload || payload.error || !thermostat) {
    setStatusPill("gateClimateStatus", payload?.error ? "error" : "none", "warn");
    setText("gateClimateInside", "--°");
    setText("gateClimateTarget", "--°");
    setText("gateClimateMode", "-");
    return;
  }
  const active = String(thermostat.hvacAction || "").toLowerCase();
  const tone = active === "cooling" || active === "heating" ? "ok" : "warn";
  setStatusPill("gateClimateStatus", thermostat.hvacActionLabel || thermostat.hvacModeLabel || "idle", tone);
  setText("gateClimateInside", thermostat.currentTemperatureF != null ? `${thermostat.currentTemperatureF}°` : "--°");
  setText("gateClimateTarget", thermostat.targetTemperatureF != null ? `${thermostat.targetTemperatureF}°` : "--°");
  setText("gateClimateMode", thermostat.hvacModeLabel || "-");
}

function paintGateSecurity(payload) {
  if (!payload || payload.error) {
    setStatusPill("gateSecurityStatus", "error", "critical");
    setText("gateDoorsOpen", "-");
    setText("gateDoorsOnline", "-");
    setText("gateCameras", "-");
    return;
  }
  const totals = payload.totals || {};
  const ha = (payload.services || []).find((service) => service.id === "home-assistant");
  const sensors = (ha && ha.details && ha.details.sensors) || [];
  const openCount = sensors.filter((sensor) => sensor.state === "Open").length;
  const onlineCount = sensors.filter((sensor) => sensor.status === "online").length;
  if (openCount > 0) setStatusPill("gateSecurityStatus", `${openCount} open`, "critical");
  else if (Number(totals.offlineCount || 0) > 0) setStatusPill("gateSecurityStatus", "degraded", "warn");
  else if (!sensors.length) setStatusPill("gateSecurityStatus", "no doors", "warn");
  else setStatusPill("gateSecurityStatus", "secure", "ok");
  setText("gateDoorsOpen", String(openCount));
  setText("gateDoorsOnline", `${onlineCount}/${sensors.length || 0}`);
  setText("gateCameras", String(totals.cameraCount || 0));
}

function paintGateFleet(fleetPayload, vmsPayload, containersPayload) {
  const totals = (fleetPayload && fleetPayload.totals) || {};
  const servers = serverRows(fleetPayload || {});
  const stale = servers.filter((item) => item.stale).length;
  const clients = (fleetPayload && fleetPayload.groups && fleetPayload.groups.clients) || [];
  const vmTotals = (vmsPayload && vmsPayload.totals) || {};
  const containerTotals = (containersPayload && containersPayload.totals) || {};

  if (!fleetPayload) {
    setStatusPill("gateFleetStatus", "error", "critical");
  } else if (stale > 0) {
    setStatusPill("gateFleetStatus", `${stale} stale`, "warn");
  } else if (!servers.length) {
    setStatusPill("gateFleetStatus", "no servers", "warn");
  } else {
    setStatusPill("gateFleetStatus", "healthy", "ok");
  }

  setText("gateServers", String(servers.length || totals.serverCount || 0));
  setText("gateStale", String(stale));
  setText("gateCpu", pct(totals.avgCpuPercent || 0));
  setText("gateVms", String(vmTotals.runningCount || 0));
  setText("gateContainers", String(containerTotals.runningCount || 0));
  setText("gateClients", String(totals.clientCount || clients.length || 0));
}

async function refreshGate() {
  const results = await Promise.allSettled([
    apiFetch(GATE_FLEET),
    apiFetch(GATE_VMS),
    apiFetch(GATE_CONTAINERS),
    apiFetch(GATE_SECURITY),
    apiFetch(GATE_WEATHER),
    apiFetch(GATE_CLIMATE),
  ]);
  const [fleet, vms, containers, security, weather, climate] = results.map((result) =>
    result.status === "fulfilled" ? result.value : null,
  );

  paintGateWeather(weather || { error: weather === null ? results[4].reason?.message : null });
  paintGateClimate(climate || { error: climate === null ? results[5].reason?.message : null });
  paintGateSecurity(security || { error: security === null ? results[3].reason?.message : null });
  paintGateFleet(fleet, vms, containers);

  const refreshSeconds = Math.min(
    60,
    ...[fleet, security, weather, climate]
      .filter(Boolean)
      .map((payload) => Number(payload.refreshSeconds || 60)),
  );
  setText("gateRefreshMeta", `Refresh ${refreshSeconds}s`);
  return refreshSeconds;
}

async function loopGate() {
  await loadBranding();
  paintGateAscii();
  paintTextBrands();
  startWallClock();
  bindAuthGates();
  const host = document.getElementById("gateHost");
  if (host) host.textContent = window.location.hostname || "192.168.1.10";

  document.getElementById("signInBtn")?.addEventListener("click", () => {
    const next = new URLSearchParams(window.location.search).get("next") || "./index.html";
    openLoginOverlay({ next });
  });

  const authed = await ensureAuth({ redirect: false }).catch(() => null);
  if (authed) {
    const redirect = new URLSearchParams(window.location.search).get("next") || "./index.html";
    window.location.href = redirect;
    return;
  }

  const autoOpen = new URLSearchParams(window.location.search).has("next");
  if (autoOpen) {
    openLoginOverlay({
      next: new URLSearchParams(window.location.search).get("next") || "./index.html",
    });
  }

  while (true) {
    const waitSec = await refreshGate();
    await new Promise((resolve) => setTimeout(resolve, Math.max(10, waitSec) * 1000));
  }
}

loopGate();
