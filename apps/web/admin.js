let inventory = [];
let releases = [];
const selectedHostIds = new Set();

function setStatus(message, isError = false) {
  const el = document.getElementById("pushStatus");
  if (!el) return;
  el.textContent = message || "";
  el.className = isError ? "admin-status error" : "admin-status";
}

function setStatusHtml(html, isError = false) {
  const el = document.getElementById("pushStatus");
  if (!el) return;
  el.innerHTML = html || "";
  el.className = isError ? "admin-status error" : "admin-status";
}

function versionStatus(row) {
  if (row.stale) return { label: "stale", tone: "warn" };
  if (row.agentVersion === "unknown") return { label: "unknown", tone: "warn" };
  if (row.updateAvailable) return { label: "update available", tone: "warn" };
  return { label: "current", tone: "ok" };
}

function updateActionStatus(row) {
  if (row.pendingUpdateCount > 0) {
    const version = row.pendingUpdateVersion ? ` → ${row.pendingUpdateVersion}` : "";
    return { label: `queued${version}`, tone: "warn" };
  }
  if (row.updateMismatch) {
    return { label: "verify restart", tone: "critical" };
  }
  if (row.lastUpdateStatus === "failed") {
    return { label: "update failed", tone: "critical" };
  }
  if (row.lastUpdateStatus === "completed") {
    return { label: "updated", tone: "ok" };
  }
  if (row.lastUpdateStatus === "delivered") {
    return { label: "delivered", tone: "warn" };
  }
  if (row.lastUpdateStatus === "queued") {
    return { label: "queued", tone: "warn" };
  }
  return { label: "—", tone: "muted" };
}

function formatPushDetails(payload) {
  const lines = [];
  if (payload.targetsResolved === 0) {
    lines.push("No hosts matched the push filters.");
  } else {
    lines.push(
      `Resolved ${payload.targetsResolved} host(s): queued ${payload.queuedCount}, skipped ${payload.skippedCount}.`,
    );
  }
  if (payload.unknownNodeIds && payload.unknownNodeIds.length) {
    lines.push(`Unknown node IDs (not in inventory): ${payload.unknownNodeIds.join(", ")}`);
  }
  (payload.queued || []).forEach((entry) => {
    const version = entry.params?.version || "?";
    lines.push(`Queued ${entry.nodeId} → v${version} (${entry.requestId})`);
  });
  (payload.skipped || []).forEach((entry) => {
    lines.push(`Skipped ${entry.nodeId}: ${entry.reason}`);
  });
  if (payload.queuedCount > 0) {
    lines.push("Agents run updates on their next heartbeat (typically within 2 minutes).");
  }
  return lines.join("\n");
}

function paintReleaseCards(platforms, platformRelease = null) {
  const container = document.getElementById("releaseCards");
  if (!container) return;
  container.innerHTML = "";
  if (platformRelease) {
    const card = document.createElement("div");
    card.className = "release-card";
    card.innerHTML = `
      <div class="release-title">${escapeHtml(platformRelease.product || "Home Command Center")}</div>
      <div class="release-version">v${escapeHtml(platformRelease.version || "0.0.0-dev")}</div>
      <div class="release-meta">Unified platform release</div>
      <div class="release-meta">${escapeHtml(platformRelease.releaseChannel || "stable")} channel</div>
    `;
    container.appendChild(card);
  }
  (platforms || []).forEach((platform) => {
    const card = document.createElement("div");
    card.className = "release-card";
    card.innerHTML = `
      <div class="release-title">${platform.platform.toUpperCase()} Agent</div>
      <div class="release-version">${platform.latestVersion}</div>
      <div class="release-meta">${platform.latestLabel || "Published release"}</div>
      <div class="release-meta">${platform.nodeCount} enrolled · ${platform.outdatedCount} outdated</div>
    `;
    container.appendChild(card);
  });
}

function paintVersionOptions(platforms) {
  const select = document.getElementById("targetVersion");
  if (!select) return;
  const previous = select.value;
  const versions = new Set();
  (platforms || []).forEach((platform) => {
    Object.keys(platform.versions || {}).forEach((version) => versions.add(version));
  });
  select.innerHTML = `<option value="">Latest per platform</option>`;
  Array.from(versions)
    .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
    .forEach((version) => {
      const option = document.createElement("option");
      option.value = version;
      option.textContent = version;
      select.appendChild(option);
    });
  if (previous && versions.has(previous)) {
    select.value = previous;
  }
}

function filteredInventory() {
  const filters = currentFilters();
  return inventory.filter((row) => {
    if (filters.platform !== "all" && row.platform !== filters.platform) return false;
    if (filters.group === "servers" && row.deviceCategory !== "server") return false;
    if (filters.group === "clients" && row.deviceCategory !== "client") return false;
    if (filters.onlyOutdated && !row.updateAvailable) return false;
    if (filters.excludeStale && row.stale) return false;
    return true;
  });
}

function syncSelectAllState(visibleRows) {
  const selectAll = document.getElementById("selectAllHosts");
  if (!selectAll) return;
  const visibleIds = visibleRows.map((row) => row.nodeId);
  const selectedVisible = visibleIds.filter((nodeId) => selectedHostIds.has(nodeId)).length;
  selectAll.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
}

function paintInventory(items = null) {
  if (Array.isArray(items)) {
    inventory = items;
    const knownIds = new Set(inventory.map((row) => row.nodeId));
    Array.from(selectedHostIds).forEach((nodeId) => {
      if (!knownIds.has(nodeId)) selectedHostIds.delete(nodeId);
    });
  }
  const visibleRows = filteredInventory();
  const tbody = document.getElementById("inventoryBody");
  const summary = document.getElementById("inventorySummary");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!visibleRows.length) {
    const message = inventory.length ? "No hosts match the active filters." : "No enrolled agents yet.";
    tbody.innerHTML = `<tr><td colspan="8">${message}</td></tr>`;
    if (summary) {
      summary.textContent = inventory.length
        ? `0 of ${inventory.length} shown | ${selectedHostIds.size} selected`
        : "0 hosts";
    }
    syncSelectAllState(visibleRows);
    return;
  }

  visibleRows.forEach((row) => {
    const status = versionStatus(row);
    const updateStatus = updateActionStatus(row);
    const selected = selectedHostIds.has(row.nodeId);
    const message = row.lastUpdateMessage
      ? `<div class="admin-cell-note" title="${escapeHtml(row.lastUpdateMessage)}">${escapeHtml(
          truncate(row.lastUpdateMessage, 72),
        )}</div>`
      : "";
    const tr = document.createElement("tr");
    tr.dataset.nodeId = row.nodeId;
    tr.classList.toggle("host-row-selected", selected);
    tr.innerHTML = `
      <td><input type="checkbox" class="host-select" data-node-id="${row.nodeId}" ${selected ? "checked" : ""} /></td>
      <td><a href="${serverPageUrl(row.nodeId)}">${row.hostname || row.nodeId}</a></td>
      <td>${row.platform || "-"}</td>
      <td>${row.hostRole || "-"}</td>
      <td>${row.agentVersion || "unknown"}</td>
      <td>${row.latestVersion || "-"}</td>
      <td>${statusPillHtml(status.label, status.tone)}</td>
      <td>${statusPillHtml(updateStatus.label, updateStatus.tone)}${message}</td>
    `;
    tbody.appendChild(tr);
  });

  const outdated = inventory.filter((row) => row.updateAvailable && !row.stale).length;
  const queued = inventory.filter((row) => row.pendingUpdateCount > 0).length;
  const failed = inventory.filter((row) => row.lastUpdateStatus === "failed").length;
  if (summary) {
    summary.textContent = `${visibleRows.length} of ${inventory.length} shown | ${selectedHostIds.size} selected | ${outdated} outdated | ${queued} queued | ${failed} failed`;
  }
  syncSelectAllState(visibleRows);
}

function paintUpdateLog(body) {
  const tbody = document.getElementById("updateLogBody");
  const summary = document.getElementById("updateLogSummary");
  if (!tbody) return;
  const items = (body?.items || []).slice().reverse();
  tbody.innerHTML = "";
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="6">No agent update activity yet.</td></tr>`;
    if (summary) summary.textContent = "0 events";
    return;
  }

  items.forEach((entry) => {
    const version = entry.params?.version || "-";
    const tone =
      entry.status === "failed"
        ? "critical"
        : entry.status === "completed"
          ? "ok"
          : entry.status === "delivered"
            ? "warn"
            : "muted";
    const when = entry.completedAt || entry.deliveredAt || entry.queuedAt || "-";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${entry.nodeId || "-"}</td>
      <td>v${version}</td>
      <td>${statusPillHtml(entry.status || "queued", tone)}</td>
      <td>${when}</td>
      <td>${escapeHtml(truncate(entry.message || "—", 120))}</td>
      <td class="mono">${entry.requestId || "-"}</td>
    `;
    tbody.appendChild(tr);
  });

  const pendingNodes = Object.keys(body?.pendingByNode || {});
  if (summary) {
    summary.textContent = `${items.length} events | ${pendingNodes.length} host(s) with pending queue`;
  }
}

function truncate(value, max) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function selectedNodeIds() {
  return Array.from(selectedHostIds);
}

function currentFilters() {
  return {
    platform: document.getElementById("filterPlatform").value,
    group: document.getElementById("filterGroup").value,
    version: document.getElementById("targetVersion").value || null,
    onlyOutdated: document.getElementById("onlyOutdated").checked,
    excludeStale: document.getElementById("excludeStale").checked,
  };
}

async function loadAdminData() {
  const [releasesBody, inventoryBody, updateLogBody, platformRelease] = await Promise.all([
    apiFetch("/api/v1/admin/agent-releases"),
    apiFetch("/api/v1/admin/agent-inventory"),
    apiFetch("/api/v1/admin/agent-updates/log?limit=40"),
    apiFetch(HCC_VERSION_ENDPOINT),
  ]);
  releases = releasesBody.platforms || [];
  paintReleaseCards(releases, platformRelease);
  paintVersionOptions(releases);
  paintInventory(inventoryBody.items || []);
  paintUpdateLog(updateLogBody);
}

async function pushUpdates({ nodeIds = null, useFilters = false }) {
  const filters = currentFilters();
  const body = {
    requestedBy: "admin-ui",
    onlyOutdated: filters.onlyOutdated,
    excludeStale: filters.excludeStale,
  };
  if (filters.version) body.version = filters.version;
  if (nodeIds && nodeIds.length) {
    body.nodeIds = nodeIds;
    body.onlyOutdated = false;
  } else if (useFilters) {
    body.platform = filters.platform;
    body.group = filters.group;
  } else {
    throw new Error("Select at least one host or use filtered push.");
  }

  const label = nodeIds && nodeIds.length
    ? `${nodeIds.length} selected host(s)`
    : `${filters.platform}/${filters.group}`;
  if (!window.confirm(`Queue agent.self_update for ${label}?`)) {
    return;
  }

  setStatus(`Queueing updates for ${label}...`);
  const payload = await apiFetch("/api/v1/admin/agent-updates/push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const isError = payload.queuedCount === 0 && payload.targetsResolved === 0;
  setStatusHtml(formatPushDetails(payload).replace(/\n/g, "<br>"), isError);
  await loadAdminData();
}

async function refreshAdmin() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    await loadAdminData();
    errorLabel.textContent = "";
  } catch (err) {
    errorLabel.textContent = `Admin fetch failed: ${err.message}`;
  }
}

document.getElementById("pushFilteredBtn").addEventListener("click", async () => {
  try {
    await pushUpdates({ useFilters: true });
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("pushSelectedBtn").addEventListener("click", async () => {
  try {
    const nodeIds = selectedNodeIds();
    if (!nodeIds.length) {
      setStatus("Select one or more hosts first.", true);
      return;
    }
    await pushUpdates({ nodeIds });
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("selectAllHosts").addEventListener("change", (event) => {
  const checked = event.target.checked;
  filteredInventory().forEach((row) => {
    if (checked) selectedHostIds.add(row.nodeId);
    else selectedHostIds.delete(row.nodeId);
  });
  paintInventory();
});

document.getElementById("inventoryBody").addEventListener("change", (event) => {
  const checkbox = event.target.closest(".host-select");
  if (!checkbox) return;
  const nodeId = checkbox.dataset.nodeId;
  if (checkbox.checked) selectedHostIds.add(nodeId);
  else selectedHostIds.delete(nodeId);
  paintInventory();
});

document.getElementById("applyFiltersBtn").addEventListener("click", () => paintInventory());

["filterPlatform", "filterGroup", "targetVersion", "onlyOutdated", "excludeStale"].forEach((id) => {
  document.getElementById(id).addEventListener("change", () => paintInventory());
});

async function loop() {
  const user = await ensureAuth();
  initAppPage("");
  paintAppNav("");
  if (user && user.role === "observer" && !user.isLocalAdmin) {
    window.location.href = "./index.html";
    return;
  }
  while (true) {
    await refreshAdmin();
    await new Promise((resolve) => setTimeout(resolve, 15000));
  }
}

loop();
