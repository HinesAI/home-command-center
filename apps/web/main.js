const FLEET_OVERVIEW_ENDPOINT = "/api/v1/fleet/overview?physicalOnly=false";
const FLEET_VMS_ENDPOINT = "/api/v1/fleet/vms";
const FLEET_CONTAINERS_ENDPOINT = "/api/v1/fleet/containers";
const SECURITY_ENDPOINT = "/api/v1/integrations/security";
const WEATHER_ENDPOINT = "/api/v1/integrations/weather";
const NETWORK_ENDPOINT = "/api/v1/integrations/network";

function paintMeter(barId, meterWrapId, labelId, percent, labelText) {
  const bar = document.getElementById(barId);
  const label = document.getElementById(labelId);
  const meterWrap = meterWrapId ? document.getElementById(meterWrapId) : bar?.closest(".meter");
  const value = Math.max(0, Math.min(100, Number(percent || 0)));
  if (label) label.textContent = labelText || pct(value);
  if (bar) {
    bar.style.width = `${value}%`;
    const tone = barClass(value);
    if (meterWrap) meterWrap.className = `meter${tone ? ` ${tone}` : ""}`;
  }
}

function serverRows(fleetPayload) {
  const groups = (fleetPayload && fleetPayload.groups) || {};
  return groups.servers || (fleetPayload.items || []).filter((item) => item.deviceCategory !== "client");
}

function paintServerHealth(fleetPayload) {
  const totals = (fleetPayload && fleetPayload.totals) || {};
  const servers = serverRows(fleetPayload);
  const serverStale = servers.filter((item) => item.stale).length;
  const memPct =
    totals.memoryTotalBytes > 0 ? (Number(totals.memoryUsedBytes || 0) * 100) / totals.memoryTotalBytes : 0;
  const storagePct =
    totals.storageTotalBytes > 0 ? (Number(totals.storageUsedBytes || 0) * 100) / totals.storageTotalBytes : 0;

  paintMeter("dashFleetCpuBar", null, "dashFleetCpu", totals.avgCpuPercent || 0);
  paintMeter(
    "dashFleetMemBar",
    null,
    "dashFleetMem",
    memPct,
    `${formatBytes(totals.memoryUsedBytes || 0)} / ${formatBytes(totals.memoryTotalBytes || 0)}`,
  );
  paintMeter(
    "dashFleetStorageBar",
    "dashFleetStorageMeter",
    "dashFleetStorage",
    storagePct,
    `${formatBytes(totals.storageUsedBytes || 0)} / ${formatBytes(totals.storageTotalBytes || 0)}`,
  );

  setText(
    "dashServerMeta",
    `${servers.length} server(s) · ${totals.serverCount || servers.length} reporting · ${serverStale} stale`,
  );

  if (serverStale > 0) {
    setStatusPill("dashServersStatus", `${serverStale} stale`, "warn");
  } else if (!servers.length) {
    setStatusPill("dashServersStatus", "no servers", "critical");
  } else {
    setStatusPill("dashServersStatus", "healthy", "ok");
  }

  const tbody = document.getElementById("dashServerTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!servers.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No servers enrolled yet.</td></tr>`;
    return;
  }

  const sorted = [...servers].sort((a, b) => {
    if (Boolean(a.stale) !== Boolean(b.stale)) return a.stale ? -1 : 1;
    return (b.resources?.cpuPercent || 0) - (a.resources?.cpuPercent || 0);
  });

  sorted.forEach((item) => {
    const tr = document.createElement("tr");
    if (item.stale) tr.className = "stale-row";
    const hostname = item.hostname || item.nodeId;
    const resources = item.resources || {};
    const stateTone = item.stale ? "warn" : "ok";
    tr.innerHTML = `
      <td><a href="${serverPageUrl(item.nodeId)}"><strong>${hostname}</strong></a></td>
      <td>${item.hostRole || "-"}</td>
      <td>${pct(resources.cpuPercent || 0)}</td>
      <td>${pct(resources.memoryPercent || 0)}</td>
      <td>${pct(resources.storagePercent || 0)}</td>
      <td>${statusPillHtml(item.stale ? "Stale" : "Online", stateTone)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function paintQuickSections(fleetPayload, vmsPayload, containersPayload) {
  const fleetTotals = (fleetPayload && fleetPayload.totals) || {};
  const vmTotals = (vmsPayload && vmsPayload.totals) || {};
  const containerTotals = (containersPayload && containersPayload.totals) || {};
  const clients = (fleetPayload && fleetPayload.groups && fleetPayload.groups.clients) || [];
  const clientStale = clients.filter((item) => item.stale).length;

  setText("dashVmRunning", String(vmTotals.runningCount || 0));
  setText("dashVmStopped", String(vmTotals.stoppedCount || 0));
  setText("dashContainerRunning", String(containerTotals.runningCount || 0));
  setText("dashContainerHosts", String(containerTotals.hostCount || 0));
  setText("dashDeviceClients", String(fleetTotals.clientCount || clients.length || 0));
  setText("dashClientStale", String(clientStale));
  setText("dashVmsStatus", (vmTotals.staleHostCount || 0) > 0 ? `${vmTotals.staleHostCount} stale hosts` : `${vmTotals.vmCount || 0} VMs`);
  setText(
    "dashContainersStatus",
    !containerTotals.hostCount
      ? "none"
      : (containerTotals.staleHostCount || 0) > 0
        ? `${containerTotals.staleHostCount} stale`
        : `${containerTotals.containerCount || 0} total`,
  );
  setText("dashClientsStatus", clientStale > 0 ? `${clientStale} stale` : "online");
}

function paintNetwork(payload) {
  const speedtest = payload && payload.speedtest;
  if (!payload || payload.error || !speedtest) {
    setText("dashWanDown", "-");
    setText("dashWanUp", "-");
    setText("dashWanPing", "-");
    if (payload && payload.error) {
      setText("dashWanStatus", payload.configured ? "error" : "not configured");
    } else {
      setText("dashWanStatus", "no results");
    }
    return;
  }
  setText("dashWanDown", speedtest.downloadMbps != null ? `${speedtest.downloadMbps} Mbps` : "-");
  setText("dashWanUp", speedtest.uploadMbps != null ? `${speedtest.uploadMbps} Mbps` : "-");
  setText("dashWanPing", speedtest.latencyMs != null ? `${speedtest.latencyMs} ms` : "-");
  const testedAt = speedtest.testedAt
    ? new Date(speedtest.testedAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : "recent";
  setText("dashWanStatus", testedAt);
}

async function refreshOverview() {
  const errorLabel = document.getElementById("errorLabel");
  const errors = [];
  let refreshSeconds = 120;

  const results = await Promise.allSettled([
    apiFetch(FLEET_OVERVIEW_ENDPOINT),
    apiFetch(FLEET_VMS_ENDPOINT),
    apiFetch(FLEET_CONTAINERS_ENDPOINT),
    apiFetch(SECURITY_ENDPOINT),
    apiFetch(WEATHER_ENDPOINT),
    apiFetch(CLIMATE_ENDPOINT),
    apiFetch(NETWORK_ENDPOINT),
  ]);

  const [fleetResult, vmsResult, containersResult, securityResult, weatherResult, climateResult, networkResult] = results;
  const fleetPayload = fleetResult.status === "fulfilled" ? fleetResult.value : null;
  const vmsPayload = vmsResult.status === "fulfilled" ? vmsResult.value : null;
  const containersPayload = containersResult.status === "fulfilled" ? containersResult.value : null;
  const securityPayload = securityResult.status === "fulfilled" ? securityResult.value : null;

  if (fleetPayload) {
    paintServerHealth(fleetPayload);
    refreshSeconds = Math.min(refreshSeconds, Number(fleetPayload.refreshSeconds || 120));
  } else {
    errors.push(`Servers: ${fleetResult.reason.message}`);
    setStatusPill("dashServersStatus", "error", "critical");
  }

  if (securityPayload) {
    paintSecurityGlance(securityPayload);
    refreshSeconds = Math.min(refreshSeconds, Number(securityPayload.refreshSeconds || 60));
  } else {
    errors.push(`Security: ${securityResult.reason.message}`);
    setStatusPill("dashSecurityStatus", "error", "critical");
    stopPreviewRefresh();
  }

  paintQuickSections(fleetPayload, vmsPayload, containersPayload);

  if (weatherResult.status === "fulfilled") {
    paintWeather(weatherResult.value);
  } else {
    paintWeather({ error: weatherResult.reason?.message || "Weather fetch failed" });
    errors.push(`Weather: ${weatherResult.reason.message}`);
  }

  if (climateResult.status === "fulfilled") {
    const user = await ensureClimateAuth();
    paintClimate(climateResult.value, {
      containerId: "dashClimateCards",
      statusId: "dashClimateStatus",
      metaId: "dashClimateMeta",
      compact: true,
      glance: true,
      interactive: canControlClimate(user),
      onUpdated: async (result, err) => {
        if (result) {
          paintClimate(result, {
            containerId: "dashClimateCards",
            statusId: "dashClimateStatus",
            metaId: "dashClimateMeta",
            compact: true,
            glance: true,
            interactive: canControlClimate(user),
          });
        }
        if (err) errors.push(`Climate: ${err.message}`);
      },
    });
    refreshSeconds = Math.min(refreshSeconds, Number(climateResult.value.refreshSeconds || 30));
  } else {
    paintClimate({ error: climateResult.reason?.message || "Climate fetch failed" }, {
      containerId: "dashClimateCards",
      statusId: "dashClimateStatus",
      metaId: "dashClimateMeta",
      compact: true,
    });
    errors.push(`Climate: ${climateResult.reason.message}`);
  }

  if (networkResult.status === "fulfilled") {
    paintNetwork(networkResult.value);
    refreshSeconds = Math.min(refreshSeconds, Number(networkResult.value.refreshSeconds || 60));
  } else {
    paintNetwork({ error: networkResult.reason?.message || "Network fetch failed" });
    errors.push(`Network: ${networkResult.reason.message}`);
  }

  if (vmsResult.status === "rejected") errors.push(`VMs: ${vmsResult.reason.message}`);
  if (containersResult.status === "rejected") errors.push(`Docker: ${containersResult.reason.message}`);

  if (errorLabel) errorLabel.textContent = errors.join(" | ");
  return refreshSeconds;
}

async function loop() {
  await ensureAuth();
  initAppPage("overview");
  while (true) {
    const waitSec = await refreshOverview();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
