const FLEET_VMS_ENDPOINT = "/api/v1/fleet/vms";

const DEFAULT_VM_ACTIONS = [
  { id: "vm.start", label: "Start", scope: "vm" },
  { id: "vm.stop", label: "Stop", scope: "vm", dangerous: true },
  { id: "vm.shutdown", label: "Shutdown", scope: "vm" },
  { id: "vm.reboot", label: "Reboot", scope: "vm" },
];

let fleetPayload = { items: [], hosts: [], totals: {} };
let filters = { status: "all", type: "all", host: "all" };

function setActionStatus(message, isError = false) {
  const el = document.getElementById("actionStatus");
  if (!el) return;
  el.textContent = message || "";
  el.style.color = isError ? "var(--bad)" : "var(--muted)";
}

function vmStatusClass(status) {
  const value = String(status || "unknown").toLowerCase();
  if (value === "running") return "status-running";
  if (value === "paused") return "status-starting";
  if (value === "stopped") return "status-stopped";
  return "status-stopped";
}

function formatVmMemory(memoryMb) {
  const value = Number(memoryMb || 0);
  if (!value) return "-";
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${value} MB`;
}

function formatVmDisk(diskGb) {
  const value = Number(diskGb || 0);
  if (!value) return "-";
  return `${value.toFixed(value >= 10 ? 0 : 1)} GB`;
}

function vmActionsForItem(item) {
  const actions = (item.actions && item.actions.length ? item.actions : DEFAULT_VM_ACTIONS).filter(
    (action) => action.scope === "vm",
  );
  return actions.filter((action) => vmActionAllowed(action.id, item.status));
}

async function runVmAction(item, action) {
  if (item.hostStale) {
    setActionStatus(`Cannot queue actions while ${item.hostname} is stale.`, true);
    return;
  }
  try {
    setActionStatus(`Queueing ${action.label || action.id} for ${item.name || item.id} on ${item.hostname}...`);
    await submitAction(item.nodeId, action.id, item.id, { vmType: item.type || "qemu" }, Boolean(action.dangerous));
    setActionStatus(
      `${action.label || action.id} queued for ${item.name || item.id}. Agent will execute on next heartbeat.`,
    );
  } catch (err) {
    setActionStatus(err.message, true);
  }
}

function buildVmActionCell(item) {
  const cell = document.createElement("td");
  const allowed = vmActionsForItem(item);
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
    btn.addEventListener("click", () => runVmAction(item, action));
    row.appendChild(btn);
  });
  cell.appendChild(row);
  return cell;
}

function buildVmRow(item) {
  const tr = document.createElement("tr");
  if (item.hostStale) tr.className = "stale-row";

  const nameCell = document.createElement("td");
  nameCell.innerHTML = `<strong>${item.name || `VM ${item.id}`}</strong>`;
  tr.appendChild(nameCell);

  tr.appendChild(rowCell(item.id));
  tr.appendChild(rowCell(String(item.type || "qemu").toUpperCase()));
  tr.appendChild(rowCell(item.osType || "-"));

  const statusCell = document.createElement("td");
  statusCell.innerHTML = statusPillHtml(item.status || "unknown", statusPillTone(item.status));
  tr.appendChild(statusCell);

  tr.appendChild(rowCell(formatVmMemory(item.memoryMb)));
  tr.appendChild(rowCell(formatVmDisk(item.diskGb)));
  tr.appendChild(rowCell(item.pid ? String(item.pid) : "-"));

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

  tr.appendChild(buildVmActionCell(item));
  return tr;
}

function rowCell(text) {
  const td = document.createElement("td");
  td.textContent = String(text);
  return td;
}

function filteredItems() {
  return (fleetPayload.items || []).filter((item) => {
    const status = String(item.status || "unknown").toLowerCase();
    const type = String(item.type || "qemu").toLowerCase();
    if (filters.status !== "all" && status !== filters.status) return false;
    if (filters.type !== "all" && type !== filters.type) return false;
    if (filters.host !== "all" && item.nodeId !== filters.host) return false;
    return true;
  });
}

function paintHostFilter() {
  const select = document.getElementById("filterHost");
  if (!select) return;
  const current = filters.host;
  select.innerHTML = `<option value="all">All hypervisors</option>`;
  (fleetPayload.hosts || []).forEach((host) => {
    const option = document.createElement("option");
    option.value = host.nodeId;
    option.textContent = `${host.hostname} (${host.vmCount})${host.stale ? " [stale]" : ""}`;
    select.appendChild(option);
  });
  select.value = [...select.options].some((option) => option.value === current) ? current : "all";
  if (select.value !== current) {
    filters.host = select.value;
  }
}

function paintVmTable() {
  const tbody = document.getElementById("vmTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = filteredItems();
  if (!(fleetPayload.hosts || []).length) {
    tbody.innerHTML =
      '<tr><td colspan="11" class="empty-state">No Proxmox hypervisors are reporting VMs yet.</td></tr>';
    return;
  }
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty-state">No virtual machines match the current filters.</td></tr>';
    return;
  }
  items.forEach((item) => tbody.appendChild(buildVmRow(item)));
}

function paintVmSummary() {
  const totals = fleetPayload.totals || {};
  setText("vmsLabel", `${totals.vmCount || 0} VM(s) across ${totals.hostCount || 0} hypervisor(s)`);
  setText("vmsTimeLabel", `Updated: ${new Date(fleetPayload.generatedAt).toLocaleString()}`);
  setText("vmTotalCount", String(totals.vmCount || 0));
  setText("vmRunningCount", String(totals.runningCount || 0));
  setText("vmStoppedCount", String(totals.stoppedCount || 0));
  setText("vmPausedCount", String(totals.pausedCount || 0));
  setText("vmHostCount", String(totals.hostCount || 0));
  setText("vmStaleHostCount", `${totals.staleHostCount || 0} stale`);
  setStatusPill(
    "vmsPageStatus",
    totals.vmCount ? `${totals.runningCount || 0} running` : "none",
    totals.staleHostCount ? "warn" : "ok",
  );
}

function bindFilters() {
  const statusSelect = document.getElementById("filterStatus");
  const typeSelect = document.getElementById("filterType");
  const hostSelect = document.getElementById("filterHost");
  if (statusSelect) {
    statusSelect.addEventListener("change", () => {
      filters.status = statusSelect.value;
      paintVmTable();
    });
  }
  if (typeSelect) {
    typeSelect.addEventListener("change", () => {
      filters.type = typeSelect.value;
      paintVmTable();
    });
  }
  if (hostSelect) {
    hostSelect.addEventListener("change", () => {
      filters.host = hostSelect.value;
      paintVmTable();
    });
  }
}

async function refreshVms() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    fleetPayload = await apiFetch(FLEET_VMS_ENDPOINT);
    paintVmSummary();
    paintHostFilter();
    paintVmTable();
    errorLabel.textContent = "";
    return Number(fleetPayload.refreshSeconds || 120);
  } catch (err) {
    errorLabel.textContent = `VM fetch failed: ${err.message}`;
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  initAppPage("vms");
  bindFilters();
  while (true) {
    const waitSec = await refreshVms();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
