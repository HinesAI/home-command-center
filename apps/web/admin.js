let inventory = [];
let releases = [];
let platformSettings = null;
const selectedHostIds = new Set();
const settingsDraft = new Map();
const ADMIN_PANELS = ["overview", "agents", "collectors", "settings"];
let updateLogCount = 0;

function showAdminPanel(panelId) {
  const active = ADMIN_PANELS.includes(panelId) ? panelId : "overview";
  ADMIN_PANELS.forEach((id) => {
    const panel = document.querySelector(`.admin-panel[data-admin-panel="${id}"]`);
    const link = document.querySelector(`#adminSubNav [data-admin-panel="${id}"]`);
    if (panel) panel.classList.toggle("hidden-panel", id !== active);
    if (link) link.classList.toggle("active", id === active);
  });
  if (window.history && window.history.replaceState) {
    window.history.replaceState(null, "", `#${active}`);
  }
}

function initAdminTabs() {
  const initial = (window.location.hash || "#overview").replace("#", "");
  showAdminPanel(initial);
  document.getElementById("adminSubNav")?.addEventListener("click", (event) => {
    const link = event.target.closest("[data-admin-panel]");
    if (!link) return;
    event.preventDefault();
    showAdminPanel(link.dataset.adminPanel);
  });
  window.addEventListener("hashchange", () => {
    const panelId = (window.location.hash || "#overview").replace("#", "");
    if (ADMIN_PANELS.includes(panelId)) showAdminPanel(panelId);
  });
}

function adminGlanceCard(title, value, meta, tone = "ok") {
  return `
    <article class="admin-glance-card">
      <p class="eyebrow">${escapeHtml(title)}</p>
      <strong class="admin-glance-value">${escapeHtml(value)}</strong>
      <p class="admin-glance-meta"><span class="status-pill ${tone}">${escapeHtml(meta)}</span></p>
    </article>
  `;
}

function paintAdminOverviewGlance() {
  const container = document.getElementById("adminOverviewGlance");
  if (!container) return;
  const migration = platformSettings?.migration;
  const collectors = platformSettings?.collectors?.collectors || [];
  const collectorErrors = collectors.filter((row) => row.status === "error").length;
  const collectorOk = collectors.filter((row) => row.status === "ok").length;
  const outdated = inventory.filter((row) => row.updateAvailable && !row.stale).length;
  const queued = inventory.filter((row) => row.pendingUpdateCount > 0).length;
  const stale = inventory.filter((row) => row.stale).length;
  const routingLabel = migration?.fullyMigrated ? "collector-only" : migration?.defaultSource || "legacy";
  const routingTone = migration?.fullyMigrated ? "ok" : "warn";

  container.innerHTML = [
    adminGlanceCard("Fleet agents", String(inventory.length), `${outdated} outdated · ${stale} stale`, outdated ? "warn" : "ok"),
    adminGlanceCard("Update queue", String(queued), `${updateLogCount} recent events`, queued ? "warn" : "ok"),
    adminGlanceCard("Collectors", `${collectorOk}/${collectors.length || 0}`, collectorErrors ? `${collectorErrors} errors` : "runtime active", collectorErrors ? "critical" : "ok"),
    adminGlanceCard("API routing", routingLabel, migration?.fullyMigrated ? "greenlit" : "legacy default", routingTone),
  ].join("");
}

function paintRoutingTable(migration) {
  const wrap = document.getElementById("settingsRoutingTable");
  if (!wrap) return;
  const services = migration?.services || [];
  if (!services.length) {
    wrap.innerHTML = "";
    return;
  }
  const rows = services
    .map((service) => {
      const sourceTone = service.source === "collector-only" ? "ok" : service.source === "collector" ? "warn" : "muted";
      return `<tr>
        <td>${escapeHtml(service.service)}</td>
        <td>${statusPillHtml(service.source, sourceTone)}</td>
        <td>${statusPillHtml(service.legacyPullEnabled ? "enabled" : "disabled", service.legacyPullEnabled ? "warn" : "ok")}</td>
        <td><code>${escapeHtml(service.collectorId || "—")}</code></td>
      </tr>`;
    })
    .join("");
  wrap.innerHTML = `
    <div class="section-header"><h3>Per-service routing</h3></div>
    <div class="table-wrap">
      <table class="fleet-table">
        <thead><tr><th>Service</th><th>API source</th><th>Legacy pull</th><th>Collector</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function setCollectorActionStatus(message, isError = false) {
  const el = document.getElementById("collectorActionStatus");
  if (!el) return;
  el.textContent = message || "";
  el.className = isError ? "admin-status error" : "admin-status";
}

function setSettingsStatus(message, isError = false) {
  const el = document.getElementById("settingsStatus");
  if (!el) return;
  el.textContent = message || "";
  el.className = isError ? "admin-status error" : "admin-status";
}

function collectorTone(status) {
  if (status === "ok") return "ok";
  if (status === "error") return "critical";
  if (status === "idle") return "muted";
  return "warn";
}

function paintCollectorStatusCards(collectorsPayload) {
  const container = document.getElementById("collectorStatusCards");
  if (!container) return;
  container.innerHTML = "";
  const collectors = (collectorsPayload && collectorsPayload.collectors) || [];
  if (!collectors.length) {
    container.innerHTML = `<div class="release-card"><div class="release-meta">Collector runtime disabled.</div></div>`;
    return;
  }
  collectors.forEach((collector) => {
    const card = document.createElement("div");
    card.className = "release-card";
    const tone = collectorTone(collector.status);
    card.innerHTML = `
      <div class="release-title">${escapeHtml(collector.id)}</div>
      <div class="release-version">${escapeHtml(collector.type)}</div>
      <div class="release-meta"><span class="status-pill ${tone}">${escapeHtml(collector.status || "idle")}</span></div>
      <div class="release-meta">${escapeHtml(String(collector.recordCount ?? "—"))} records · ${collector.intervalSeconds || "?"}s</div>
      <div class="release-meta">${collector.lastError ? escapeHtml(collector.lastError) : `Last run ${escapeHtml(collector.lastRunAt || "—")}`}</div>
    `;
    container.appendChild(card);
  });
}

function paintMigrationBanner(migration) {
  const banner = document.getElementById("settingsMigrationBanner");
  const summary = document.getElementById("settingsSummary");
  if (!banner || !migration) return;
  const migrated = (migration.migratedServices || []).join(", ") || "none";
  banner.innerHTML = `
    <div class="settings-banner-card">
      <strong>Integration routing</strong>
      <span>Default source: <code>${escapeHtml(migration.defaultSource || "legacy")}</code></span>
      <span>Migrated: <code>${escapeHtml(migrated)}</code></span>
      <span>${migration.fullyMigrated ? "Fully on collectors" : "Dashboard APIs still on legacy until greenlight"}</span>
    </div>
  `;
  if (summary) {
    summary.textContent = migration.fullyMigrated ? "collector-only" : migration.defaultSource || "legacy";
    summary.className = `status-pill ${migration.fullyMigrated ? "ok" : "warn"}`;
  }
}

function paintSettingsActions(actions) {
  const container = document.getElementById("settingsActions");
  if (!container) return;
  container.innerHTML = "";
  (actions || []).forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = action.id.includes("rollback") ? "action-button secondary" : "action-button warn";
    button.textContent = action.label;
    button.title = action.description || "";
    button.dataset.actionId = action.id;
    button.addEventListener("click", () => runSettingsAction(action.id));
    container.appendChild(button);
  });
}

function settingsInputId(key) {
  return `setting-${key.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function paintSettingsGroups(payload) {
  const container = document.getElementById("settingsGroups");
  if (!container || !payload) return;
  container.innerHTML = "";
  settingsDraft.clear();
  (payload.schema.groups || []).forEach((group, index) => {
    const section = document.createElement("details");
    section.className = "settings-group";
    section.open = index === 0;
    section.innerHTML = `
      <summary class="settings-group-summary">
        <span class="settings-group-title">${escapeHtml(group.label)}</span>
        <span class="settings-group-count">${(group.fields || []).length} options</span>
      </summary>
      <div class="settings-group-body">
        <p class="settings-group-description">${escapeHtml(group.description || "")}</p>
        <div class="settings-grid"></div>
      </div>
    `;
    const grid = section.querySelector(".settings-grid");
    (group.fields || []).forEach((field) => {
      const valueEntry = payload.values[field.key] || { value: field.default || "" };
      const currentValue = valueEntry.value ?? field.default ?? "";
      settingsDraft.set(field.key, currentValue);
      const fieldEl = document.createElement("label");
      fieldEl.className = "settings-field";
      fieldEl.htmlFor = settingsInputId(field.key);
      let control = "";
      if (field.type === "bool" || (field.type === "enum" && field.options && field.options.length)) {
        const options = field.type === "bool" ? ["true", "false"] : field.options;
        control = `<select id="${settingsInputId(field.key)}" data-setting-key="${field.key}">
          ${options
            .map((option) => `<option value="${escapeHtml(option)}" ${String(currentValue) === option ? "selected" : ""}>${escapeHtml(option)}</option>`)
            .join("")}
        </select>`;
      } else if (field.secret) {
        control = `<input id="${settingsInputId(field.key)}" data-setting-key="${field.key}" type="password" value="" placeholder="${escapeHtml(valueEntry.configured ? "Leave blank to keep current" : "Not configured")}" autocomplete="new-password" />`;
      } else {
        control = `<input id="${settingsInputId(field.key)}" data-setting-key="${field.key}" type="${field.type === "int" || field.type === "float" ? "number" : "text"}" value="${escapeHtml(String(currentValue))}" />`;
      }
      const meta = [
        field.cliFlag ? `<code>${escapeHtml(field.cliFlag)}</code>` : "",
        field.hotReload ? "hot reload" : "",
        field.restartRequired ? "restart required" : "",
      ]
        .filter(Boolean)
        .join(" · ");
      fieldEl.innerHTML = `
        <span class="settings-label">${escapeHtml(field.label)}</span>
        ${control}
        <small>${escapeHtml(field.description || field.key)}</small>
        ${meta ? `<small class="settings-meta">${meta}</small>` : ""}
      `;
      grid.appendChild(fieldEl);
    });
    container.appendChild(section);
  });
}

function collectSettingsUpdates() {
  const updates = {};
  document.querySelectorAll("[data-setting-key]").forEach((input) => {
    const key = input.dataset.settingKey;
    const original = settingsDraft.get(key);
    const value = input.value;
    if (input.type === "password") {
      if (!value) return;
      updates[key] = value;
      return;
    }
    if (String(original ?? "") !== String(value ?? "")) {
      updates[key] = value;
    }
  });
  return updates;
}

async function loadSettings() {
  platformSettings = await apiFetch("/api/v1/admin/settings");
  paintMigrationBanner(platformSettings.migration);
  paintCollectorStatusCards(platformSettings.collectors);
  paintRoutingTable(platformSettings.migration);
  paintSettingsActions(platformSettings.actions);
  paintSettingsGroups(platformSettings);
  paintAdminOverviewGlance();
}

async function saveSettings() {
  const updates = collectSettingsUpdates();
  if (!Object.keys(updates).length) {
    setSettingsStatus("No changes to save.", true);
    return;
  }
  setSettingsStatus("Saving settings...");
  const result = await apiFetch("/api/v1/admin/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates }),
  });
  if (!result.ok) {
    setSettingsStatus((result.errors || [result.error || "Save failed"]).join("; "), true);
    return;
  }
  const restartNote = result.restartRequired ? " Restart Core to apply collector runtime changes." : "";
  setSettingsStatus(`Saved ${result.updated.length} setting(s) to ${result.settingsFile}.${restartNote}`);
  await loadSettings();
}

async function runSettingsAction(actionId) {
  const path =
    actionId === "greenlight-collectors"
      ? "/api/v1/admin/settings/actions/greenlight-collectors"
      : actionId === "rollback-collectors"
        ? "/api/v1/admin/settings/actions/rollback-collectors"
        : null;
  if (!path) return;
  const label = actionId === "greenlight-collectors" ? "greenlight collector migration" : "rollback collector migration";
  if (!window.confirm(`Run ${label}?`)) return;
  setSettingsStatus(`Running ${label}...`);
  setCollectorActionStatus(`Running ${label}...`);
  const result = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!result.ok) {
    const message = (result.errors || [result.error || "Action failed"]).join("; ");
    setSettingsStatus(message, true);
    setCollectorActionStatus(message, true);
    return;
  }
  const success = `${label} applied to ${(result.services || []).join(", ")}.${result.restartRequired ? " Restart Core if collector runtime flags changed." : ""}`;
  setSettingsStatus(success);
  setCollectorActionStatus(success);
  await loadSettings();
}

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
  paintAdminOverviewGlance();
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
    updateLogCount = 0;
    paintAdminOverviewGlance();
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
  updateLogCount = items.length;
  paintAdminOverviewGlance();
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
  await loadSettings();
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

document.getElementById("saveSettingsBtn")?.addEventListener("click", async () => {
  try {
    await saveSettings();
  } catch (err) {
    setSettingsStatus(err.message, true);
  }
});

document.getElementById("reloadSettingsBtn")?.addEventListener("click", async () => {
  try {
    await loadSettings();
    setSettingsStatus("Settings reloaded.");
  } catch (err) {
    setSettingsStatus(err.message, true);
  }
});

["filterPlatform", "filterGroup", "targetVersion", "onlyOutdated", "excludeStale"].forEach((id) => {
  document.getElementById(id).addEventListener("change", () => paintInventory());
});

async function loop() {
  const user = await ensureAuth();
  initAppPage("");
  paintAppNav("");
  initAdminTabs();
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
