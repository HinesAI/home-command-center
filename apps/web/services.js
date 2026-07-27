const FLEET_SERVICES_ENDPOINT = "/api/v1/fleet/services";

const DEFAULT_SERVICE_ACTIONS = [
  { id: "service.start", label: "Start", scope: "service" },
  { id: "service.stop", label: "Stop", scope: "service", dangerous: true },
  { id: "service.restart", label: "Restart", scope: "service" },
];

let fleetPayload = { items: [], hosts: [], totals: {} };
let filters = { status: "all", host: "all", platform: "all", view: "table" };

function setActionStatus(message, isError = false) {
  const el = document.getElementById("actionStatus");
  if (!el) return;
  el.textContent = message || "";
  el.style.color = isError ? "var(--bad)" : "var(--muted)";
}

function serviceActionsForItem(item) {
  const actions = (item.actions && item.actions.length ? item.actions : DEFAULT_SERVICE_ACTIONS).filter(
    (action) => action.scope === "service",
  );
  return actions.filter((action) => serviceActionAllowed(action.id, item.status));
}

async function runServiceAction(item, action) {
  if (item.hostStale) {
    setActionStatus(`Cannot queue actions while ${item.hostname} is stale.`, true);
    return;
  }
  try {
    setActionStatus(`Queueing ${action.label || action.id} for ${item.name} on ${item.hostname}...`);
    await submitAction(item.nodeId, action.id, item.name, {}, Boolean(action.dangerous));
    setActionStatus(`${action.label || action.id} queued for ${item.name}. Agent will execute on next heartbeat.`);
  } catch (err) {
    setActionStatus(err.message, true);
  }
}

function buildServiceActionCell(item) {
  const cell = document.createElement("td");
  const allowed = serviceActionsForItem(item);
  if (item.hostStale) {
    cell.innerHTML = `<span class="cell-sub">Host stale</span>`;
    return cell;
  }
  if (!allowed.length) {
    cell.innerHTML = `<span class="cell-sub">No actions</span>`;
    return cell;
  }
  const row = document.createElement("div");
  row.className = "action-row";
  allowed.forEach((action) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `action-button${action.dangerous ? " warn" : ""}`;
    btn.textContent = action.label || action.id;
    btn.addEventListener("click", () => runServiceAction(item, action));
    row.appendChild(btn);
  });
  cell.appendChild(row);
  return cell;
}

function rowCell(text) {
  const td = document.createElement("td");
  td.textContent = String(text);
  return td;
}

function buildServiceRow(item) {
  const tr = document.createElement("tr");
  if (item.hostStale) tr.className = "stale-row";

  const nameCell = document.createElement("td");
  nameCell.innerHTML = `<strong>${item.name}</strong>`;
  tr.appendChild(nameCell);

  const statusCell = document.createElement("td");
  statusCell.innerHTML = statusPillHtml(item.statusText || item.status || "unknown", statusPillTone(item.status));
  tr.appendChild(statusCell);

  const hostCell = document.createElement("td");
  const hostLink = document.createElement("a");
  hostLink.href = serverPageUrl(item.nodeId);
  hostLink.className = "inline-link";
  hostLink.textContent = item.hostname || item.nodeId;
  hostCell.appendChild(hostLink);
  tr.appendChild(hostCell);

  tr.appendChild(rowCell(item.platform || "-"));
  tr.appendChild(rowCell(item.hostRole || "-"));

  const hostStateCell = document.createElement("td");
  hostStateCell.innerHTML = statusPillHtml(item.hostStale ? "stale" : "online", item.hostStale ? "warn" : "ok");
  tr.appendChild(hostStateCell);

  tr.appendChild(buildServiceActionCell(item));
  return tr;
}

function filteredItems() {
  return (fleetPayload.items || []).filter((item) => {
    const status = String(item.status || "unknown").toLowerCase();
    if (filters.status !== "all" && status !== filters.status) return false;
    if (filters.host !== "all" && item.nodeId !== filters.host) return false;
    if (filters.platform !== "all" && String(item.platform || "").toLowerCase() !== filters.platform) return false;
    return true;
  });
}

function paintHostFilter() {
  const select = document.getElementById("filterHost");
  if (!select) return;
  const current = filters.host;
  select.innerHTML = `<option value="all">All hosts</option>`;
  (fleetPayload.hosts || []).forEach((host) => {
    const option = document.createElement("option");
    option.value = host.nodeId;
    option.textContent = `${host.hostname} (${host.serviceCount})${host.stale ? " [stale]" : ""}`;
    select.appendChild(option);
  });
  select.value = [...select.options].some((option) => option.value === current) ? current : "all";
  if (select.value !== current) {
    filters.host = select.value;
  }
}

function paintGroupedServices(items) {
  const container = document.getElementById("groupedServicesView");
  if (!container) return;
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<p class="empty-state">No services match the current filters.</p>`;
    return;
  }

  const groups = new Map();
  items.forEach((item) => {
    const key = String(item.name || "unknown").toLowerCase();
    if (!groups.has(key)) groups.set(key, { name: item.name, items: [] });
    groups.get(key).items.push(item);
  });

  [...groups.values()]
    .sort((a, b) => a.name.localeCompare(b.name))
    .forEach((group) => {
      const section = document.createElement("article");
      section.className = "overview-section grouped-service-block";
      const running = group.items.filter((item) => item.status === "running").length;
      section.innerHTML = `
        <div class="section-header">
          <h3>${group.name}</h3>
          <span class="cell-sub">${running}/${group.items.length} running across ${new Set(group.items.map((i) => i.nodeId)).size} host(s)</span>
        </div>
      `;
      const table = document.createElement("table");
      table.className = "fleet-table";
      table.innerHTML = `<thead><tr><th>Status</th><th>Host</th><th>Platform</th><th>Actions</th></tr></thead>`;
      const tbody = document.createElement("tbody");
      group.items
        .sort((a, b) => String(a.hostname).localeCompare(String(b.hostname)))
        .forEach((item) => {
          const tr = document.createElement("tr");
          if (item.hostStale) tr.className = "stale-row";
          const statusCell = document.createElement("td");
          statusCell.innerHTML = statusPillHtml(item.statusText || item.status || "unknown", statusPillTone(item.status));
          tr.appendChild(statusCell);
          const hostCell = document.createElement("td");
          hostCell.innerHTML = `<a class="inline-link" href="${serverPageUrl(item.nodeId)}">${item.hostname || item.nodeId}</a>`;
          tr.appendChild(hostCell);
          tr.appendChild(rowCell(item.platform || "-"));
          tr.appendChild(buildServiceActionCell(item));
          tbody.appendChild(tr);
        });
      table.appendChild(tbody);
      section.appendChild(table);
      container.appendChild(section);
    });
}

function paintServiceTable() {
  const tbody = document.getElementById("serviceTableBody");
  const tableWrap = document.getElementById("servicesTableWrap");
  const groupedView = document.getElementById("groupedServicesView");
  if (!tbody || !tableWrap || !groupedView) return;

  const items = filteredItems();
  const grouped = filters.view === "grouped";
  tableWrap.classList.toggle("hidden-panel", grouped);
  groupedView.classList.toggle("hidden-panel", !grouped);

  if (!(fleetPayload.hosts || []).length) {
    tbody.innerHTML =
      '<tr><td colspan="7" class="empty-state">No hosts are reporting monitored services yet.</td></tr>';
    groupedView.innerHTML = `<p class="empty-state">No hosts are reporting monitored services yet.</p>`;
    return;
  }

  if (grouped) {
    paintGroupedServices(items);
    return;
  }

  tbody.innerHTML = "";
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No services match the current filters.</td></tr>';
    return;
  }
  items.forEach((item) => tbody.appendChild(buildServiceRow(item)));
}

function paintServiceSummary() {
  const totals = fleetPayload.totals || {};
  setText("servicesLabel", `${totals.serviceCount || 0} service(s) across ${totals.hostCount || 0} host(s)`);
  setText("servicesTimeLabel", `Updated: ${new Date(fleetPayload.generatedAt).toLocaleString()}`);
  setText("serviceTotalCount", String(totals.serviceCount || 0));
  setText("serviceRunningCount", String(totals.runningCount || 0));
  setText("serviceStoppedCount", String(totals.stoppedCount || 0));
  setText("serviceHostCount", String(totals.hostCount || 0));
  setText("serviceStaleHostCount", `${totals.staleHostCount || 0} stale`);
  setStatusPill(
    "servicesPageStatus",
    totals.hostCount ? `${totals.runningCount || 0} running` : "none",
    totals.staleHostCount || totals.stoppedCount ? "warn" : "ok",
  );
}

function bindFilters() {
  const statusSelect = document.getElementById("filterStatus");
  const hostSelect = document.getElementById("filterHost");
  const platformSelect = document.getElementById("filterPlatform");
  const viewSelect = document.getElementById("filterView");

  const repaint = () => paintServiceTable();

  if (statusSelect) {
    statusSelect.addEventListener("change", () => {
      filters.status = statusSelect.value;
      repaint();
    });
  }
  if (hostSelect) {
    hostSelect.addEventListener("change", () => {
      filters.host = hostSelect.value;
      repaint();
    });
  }
  if (platformSelect) {
    platformSelect.addEventListener("change", () => {
      filters.platform = platformSelect.value;
      repaint();
    });
  }
  if (viewSelect) {
    viewSelect.addEventListener("change", () => {
      filters.view = viewSelect.value;
      repaint();
    });
  }
}

async function refreshServices() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    fleetPayload = await apiFetch(FLEET_SERVICES_ENDPOINT);
    paintServiceSummary();
    paintHostFilter();
    paintServiceTable();
    errorLabel.textContent = "";
    return Number(fleetPayload.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Service fetch failed: ${err.message}`;
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  initAppPage("services");
  bindFilters();
  while (true) {
    const waitSec = await refreshServices();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
