const FLEET_OVERVIEW_ENDPOINT = "/api/v1/fleet/overview?physicalOnly=false";

const DEVICES_SUBNAV = [
  { id: "all", href: "./devices.html", label: "Overview" },
  { id: "servers", href: "./devices-servers.html", label: "Servers" },
  { id: "clients", href: "./devices-clients.html", label: "Clients" },
];

function buildDeviceCard(item) {
  const card = document.createElement("a");
  card.href = serverPageUrl(item.nodeId);
  card.className = "host-card host-card-link";
  const tone = item.stale ? "warn" : "ok";
  card.innerHTML = `
    <header>
      <div><h3>${item.hostname || item.nodeId}</h3><span>${item.hostRole || "host"}</span></div>
      ${statusPillHtml(item.stale ? "Stale" : "Online", tone)}
    </header>
    <p>${osText(item)} · ${item.ips && item.ips.length ? item.ips[0] : "no ip"}</p>
    <div class="mini-meters">
      <div class="mini-meter"><span>CPU</span><div class="meter"><span style="width:${Math.min(100, item.resources?.cpuPercent || 0)}%"></span></div><strong>${pct(item.resources?.cpuPercent || 0)}</strong></div>
      <div class="mini-meter"><span>MEM</span><div class="meter"><span style="width:${Math.min(100, item.resources?.memoryPercent || 0)}%"></span></div><strong>${pct(item.resources?.memoryPercent || 0)}</strong></div>
      <div class="mini-meter"><span>DSK</span><div class="meter"><span style="width:${Math.min(100, item.resources?.storagePercent || 0)}%"></span></div><strong>${pct(item.resources?.storagePercent || 0)}</strong></div>
    </div>
    <small>Uptime ${formatUptime(item.uptimeSec || 0)} · ${formatLoadLabel(item.resources, item.platform)}</small>
  `;
  return card;
}

function paintDeviceCards(containerId, items, emptyText) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  container.className = "card-grid";
  if (!items.length) {
    container.innerHTML = `<p class="empty-state">${emptyText}</p>`;
    return;
  }
  const sorted = [...items].sort((a, b) => {
    if (Boolean(a.stale) !== Boolean(b.stale)) return a.stale ? -1 : 1;
    return (a.hostname || a.nodeId).localeCompare(b.hostname || b.nodeId);
  });
  sorted.forEach((item) => container.appendChild(buildDeviceCard(item)));
}

function splitFleetGroups(fleetOverview) {
  const groups = fleetOverview.groups || {};
  const servers = groups.servers || (fleetOverview.items || []).filter((item) => item.deviceCategory !== "client");
  const clients = groups.clients || (fleetOverview.items || []).filter((item) => item.deviceCategory === "client");
  return { servers, clients, totals: fleetOverview.totals || {} };
}

async function fetchFleetOverview() {
  return apiFetch(FLEET_OVERVIEW_ENDPOINT);
}

function paintDevicesSummary(fleetOverview) {
  const { servers, clients, totals } = splitFleetGroups(fleetOverview);
  setText("devicesLabel", `${totals.nodeCount || 0} enrolled (${totals.staleCount || 0} stale)`);
  setText("devicesTimeLabel", `Updated: ${new Date(fleetOverview.generatedAt).toLocaleString()}`);
  setText("devicesTotalCount", String(totals.nodeCount || 0));
  setText("devicesServerCount", String(totals.serverCount ?? servers.length ?? 0));
  setText("devicesClientCount", String(totals.clientCount ?? clients.length ?? 0));
  setText("devicesStaleCount", String(totals.staleCount || 0));
  const staleStat = document.getElementById("devicesStaleCountStat");
  if (staleStat) staleStat.textContent = String(totals.staleCount || 0);
  const stalePill = document.getElementById("devicesStalePill");
  if (stalePill) {
    const stale = Number(totals.staleCount || 0);
    setStatusPill("devicesStalePill", stale ? `${stale} stale` : "nominal", stale ? "warn" : "ok");
  }
  return { servers, clients, totals };
}

function paintDevicesSubNav(active) {
  paintSubNav("devicesSubNav", DEVICES_SUBNAV, active);
}

async function startDevicesPage(refreshPage, subNavActive) {
  await ensureAuth();
  initAppPage("devices");
  paintDevicesSubNav(subNavActive);
  while (true) {
    const waitSec = await refreshPage();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}
