const FLEET_CONTAINERS_ENDPOINT = "/api/v1/fleet/containers";

const DEFAULT_CONTAINER_ACTIONS = [
  { id: "container.start", label: "Start", scope: "container" },
  { id: "container.stop", label: "Stop", scope: "container", dangerous: true },
  { id: "container.restart", label: "Restart", scope: "container" },
];

let fleetPayload = { items: [], hosts: [], totals: {} };
let filters = { status: "all", host: "all" };

function setActionStatus(message, isError = false) {
  const el = document.getElementById("actionStatus");
  if (!el) return;
  el.textContent = message || "";
  el.style.color = isError ? "var(--bad)" : "var(--muted)";
}

function containerStatusClass(status) {
  return statusClass(status);
}

function formatContainerMemory(item) {
  const used = Number(item.memoryUsedBytes || 0);
  const limit = Number(item.memoryLimitBytes || 0);
  if (!used && !limit) {
    return item.status === "running" ? "-" : "n/a";
  }
  if (limit) {
    return `${formatBytes(used)} / ${formatBytes(limit)}`;
  }
  return formatBytes(used);
}

function containerActionsForItem(item) {
  const actions = (item.actions && item.actions.length ? item.actions : DEFAULT_CONTAINER_ACTIONS).filter(
    (action) => action.scope === "container",
  );
  return actions.filter((action) => containerActionAllowed(action.id, item.status));
}

async function runContainerAction(item, action) {
  if (item.hostStale) {
    setActionStatus(`Cannot queue actions while ${item.hostname} is stale.`, true);
    return;
  }
  try {
    setActionStatus(`Queueing ${action.label || action.id} for ${item.name} on ${item.hostname}...`);
    await submitAction(item.nodeId, action.id, item.name, {}, Boolean(action.dangerous));
    setActionStatus(
      `${action.label || action.id} queued for ${item.name}. Agent will execute on next heartbeat.`,
    );
  } catch (err) {
    setActionStatus(err.message, true);
  }
}

function buildContainerActionCell(item) {
  const cell = document.createElement("td");
  const allowed = containerActionsForItem(item);
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
    btn.addEventListener("click", () => runContainerAction(item, action));
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

function buildContainerRow(item) {
  const tr = document.createElement("tr");
  if (item.hostStale) tr.className = "stale-row";

  const nameCell = document.createElement("td");
  nameCell.innerHTML = `<strong>${item.name}</strong><div class="cell-sub">${item.id || "-"}</div>`;
  tr.appendChild(nameCell);
  tr.appendChild(rowCell(item.image || "-"));

  const statusCell = document.createElement("td");
  statusCell.innerHTML = statusPillHtml(item.statusText || item.status || "unknown", statusPillTone(item.status));
  tr.appendChild(statusCell);

  tr.appendChild(rowCell(item.cpuPercent != null ? pct(item.cpuPercent) : "-"));
  tr.appendChild(rowCell(formatContainerMemory(item)));
  tr.appendChild(rowCell(item.networkIo || "-"));

  const hostCell = document.createElement("td");
  const hostLink = document.createElement("a");
  hostLink.href = serverPageUrl(item.nodeId);
  hostLink.className = "inline-link";
  hostLink.textContent = item.hostname || item.nodeId;
  hostCell.appendChild(hostLink);
  tr.appendChild(hostCell);

  const hostStateCell = document.createElement("td");
  hostStateCell.innerHTML = statusPillHtml(item.hostStale ? "stale" : "online", item.hostStale ? "warn" : "ok");
  tr.appendChild(hostStateCell);

  tr.appendChild(buildContainerActionCell(item));
  return tr;
}

function filteredItems() {
  return (fleetPayload.items || []).filter((item) => {
    const status = String(item.status || "unknown").toLowerCase();
    if (filters.status !== "all" && status !== filters.status) return false;
    if (filters.host !== "all" && item.nodeId !== filters.host) return false;
    return true;
  });
}

function paintHostFilter() {
  const select = document.getElementById("filterHost");
  if (!select) return;
  const current = filters.host;
  select.innerHTML = `<option value="all">All Docker hosts</option>`;
  (fleetPayload.hosts || []).forEach((host) => {
    const option = document.createElement("option");
    option.value = host.nodeId;
    option.textContent = `${host.hostname} (${host.containerCount})${host.stale ? " [stale]" : ""}`;
    select.appendChild(option);
  });
  select.value = [...select.options].some((option) => option.value === current) ? current : "all";
  if (select.value !== current) {
    filters.host = select.value;
  }
}

function paintContainerTable() {
  const tbody = document.getElementById("containerTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = filteredItems();
  if (!(fleetPayload.hosts || []).length) {
    tbody.innerHTML =
      '<tr><td colspan="9" class="empty-state">No Linux hosts with Docker are reporting containers yet.</td></tr>';
    return;
  }
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No containers match the current filters.</td></tr>';
    return;
  }
  items.forEach((item) => tbody.appendChild(buildContainerRow(item)));
}

function paintContainerSummary() {
  const totals = fleetPayload.totals || {};
  setText(
    "containersLabel",
    `${totals.containerCount || 0} docker container(s) across ${totals.hostCount || 0} host(s)`,
  );
  setText("containersTimeLabel", `Updated: ${new Date(fleetPayload.generatedAt).toLocaleString()}`);
  setText("containerTotalCount", String(totals.containerCount || 0));
  setText("containerRunningCount", String(totals.runningCount || 0));
  setText("containerStoppedCount", String(totals.stoppedCount || 0));
  setText("containerHostCount", String(totals.hostCount || 0));
  setText("containerStaleHostCount", `${totals.staleHostCount || 0} stale`);
  setStatusPill(
    "containersPageStatus",
    totals.hostCount ? `${totals.runningCount || 0} running` : "none",
    totals.staleHostCount ? "warn" : "ok",
  );
}

function bindFilters() {
  const statusSelect = document.getElementById("filterStatus");
  const hostSelect = document.getElementById("filterHost");
  if (statusSelect) {
    statusSelect.addEventListener("change", () => {
      filters.status = statusSelect.value;
      paintContainerTable();
    });
  }
  if (hostSelect) {
    hostSelect.addEventListener("change", () => {
      filters.host = hostSelect.value;
      paintContainerTable();
    });
  }
}

async function refreshContainers() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    fleetPayload = await apiFetch(FLEET_CONTAINERS_ENDPOINT);
    paintContainerSummary();
    paintHostFilter();
    paintContainerTable();
    errorLabel.textContent = "";
    return Number(fleetPayload.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `Container fetch failed: ${err.message}`;
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  initAppPage("containers");
  bindFilters();
  while (true) {
    const waitSec = await refreshContainers();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
