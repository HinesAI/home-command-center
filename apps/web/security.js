const SECURITY_ENDPOINT = "/api/v1/integrations/security";
const PREVIEW_REFRESH_MS = 2500;

let securityPayload = { services: [], totals: {} };
let activePanel = "overview";
let previewRefreshTimer = null;
let recordingControlUser = null;
let recordingPending = false;

function canControlRecording(user) {
  if (!user) return false;
  if (user.isLocalAdmin) return true;
  const rank = { observer: 0, operator: 1, maintainer: 2, deployer: 3 };
  return (rank[user.role] || 0) >= 1;
}

async function ensureRecordingAuth() {
  if (recordingControlUser !== null) return recordingControlUser;
  try {
    const body = await fetchCurrentUser();
    recordingControlUser = body.user || null;
  } catch (_err) {
    recordingControlUser = null;
  }
  return recordingControlUser;
}

function paintSecuritySubNav(active) {
  paintSubNav(
    "securitySubNav",
    [
      { id: "overview", label: "Overview" },
      { id: "frigate", label: "Frigate" },
      { id: "home-assistant", label: "Home Assistant" },
    ],
    active,
    { useButtons: true },
  );
  document.querySelectorAll("#securitySubNav [data-panel]").forEach((button) => {
    button.addEventListener("click", () => showSecurityPanel(button.dataset.panel));
  });
  document.querySelectorAll("[data-panel-jump]").forEach((button) => {
    button.addEventListener("click", () => showSecurityPanel(button.dataset.panelJump));
  });
}

function showSecurityPanel(panelId) {
  activePanel = panelId;
  paintSecuritySubNav(panelId);
  const visible = {
    overview: ["securitySummaryPanel", "securityOverviewPanel"],
    frigate: ["frigatePanel", "frigateEmbedPanel"],
    "home-assistant": ["haPanel"],
  }[panelId] || [];
  ["securitySummaryPanel", "securityOverviewPanel", "frigatePanel", "frigateEmbedPanel", "haPanel"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("hidden-panel", !visible.includes(id));
  });
  if (panelId !== "overview") {
    stopPreviewRefresh();
  } else if (document.querySelectorAll("#overviewCameraPreviews img[data-preview-base]").length) {
    startPreviewRefresh();
  }
}

function serviceById(serviceId) {
  return (securityPayload.services || []).find((service) => service.id === serviceId);
}

function paintSecuritySummary() {
  const totals = securityPayload.totals || {};
  setText("securityLabel", `${totals.onlineCount || 0}/${totals.serviceCount || 0} services online`);
  setText("securityTimeLabel", `Updated: ${new Date(securityPayload.generatedAt).toLocaleString()}`);
  setText("securityServiceCount", String(totals.serviceCount || 0));
  setText("securityOnlineCount", String(totals.onlineCount || 0));
  setText("securityOfflineCount", String(totals.offlineCount || 0));
  setText("securityCameraCount", String(totals.cameraCount || 0));
  setText("securitySensorCount", String(totals.sensorCount || 0));
}

function buildSecurityCard(service) {
  const card = document.createElement("article");
  card.className = "platform-card platform-card-live";
  const details = service.details || {};
  const detailLines = [];
  if (service.id === "frigate") {
    if (details.version) detailLines.push(`Version ${details.version}`);
    detailLines.push(
      `${details.cameraCount || 0} camera(s), ${details.onlineCameraCount || 0} online, ${
        details.detectionEnabledCount || 0
      } detecting, ${details.recordingEnabledCount || 0} recording`,
    );
    const schedule = details.schedule || {};
    if (schedule.window) {
      detailLines.push(`Schedule ${schedule.window}${schedule.active ? " (in window)" : ""}`);
    }
  } else if (service.id === "home-assistant") {
    const sensors = details.sensorCount || 0;
    if (details.sensorsConfigured) {
      detailLines.push(`${sensors} door sensor(s), ${details.sensorOnlineCount || 0} reporting`);
    } else {
      detailLines.push("Sensor API token not configured");
    }
  }
  if (service.latencyMs != null) detailLines.push(`${service.latencyMs} ms`);
  if (service.error) detailLines.push(service.error);

  card.innerHTML = `
    <header>
      <div><h3>${service.name}</h3><span>${service.host}</span></div>
      ${statusPillHtml(service.online ? "online" : "offline", service.online ? "ok" : "critical")}
    </header>
    <p>${detailLines.join(" | ") || "No details"}</p>
    <div class="action-row"><a class="action-button" href="${service.dashboardUrl}" target="_blank" rel="noopener">Open ${service.name}</a></div>
  `;
  return card;
}

function paintSecurityCards() {
  const container = document.getElementById("securityCards");
  if (!container) return;
  container.innerHTML = "";
  const services = securityPayload.services || [];
  if (!services.length) {
    container.innerHTML = `<p class="empty-state">No security integrations configured.</p>`;
    return;
  }
  services.forEach((service) => container.appendChild(buildSecurityCard(service)));
}

function formatHaTimestamp(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function paintDoorRows(tbody, ha, compact = false) {
  if (!tbody) return;
  tbody.innerHTML = "";
  const details = (ha && ha.details) || {};
  const sensors = details.sensors || [];
  const colSpan = compact ? 3 : 4;

  if (!ha || !ha.online) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">${ha && ha.error ? ha.error : "Home Assistant is offline"}</td></tr>`;
    return;
  }
  if (!details.sensorsConfigured) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">Configure HCC_HA_TOKEN on core to load door sensors.</td></tr>`;
    return;
  }
  if (details.error && !sensors.length) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">${details.error}</td></tr>`;
    return;
  }
  if (!sensors.length) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">No door sensors found.</td></tr>`;
    return;
  }

  sensors.forEach((sensor) => {
    const tr = document.createElement("tr");
    const stateClass = sensor.stateClass || (sensor.state === "Open" ? "status-stopped" : "status-running");
    tr.innerHTML = compact
      ? `
      <td><strong>${sensor.name}</strong></td>
      <td>${statusPillHtml(sensor.state, sensor.state === "Open" ? "critical" : statusPillTone(sensor.status))}</td>
      <td>${statusPillHtml(sensor.status, statusPillTone(sensor.status))}</td>
    `
      : `
      <td><strong>${sensor.name}</strong><div class="cell-sub">${sensor.entityId}</div></td>
      <td>${statusPillHtml(sensor.state, sensor.state === "Open" ? "critical" : statusPillTone(sensor.status))}</td>
      <td>${statusPillHtml(sensor.status, statusPillTone(sensor.status))}</td>
      <td>${formatHaTimestamp(sensor.lastChanged)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function paintHaSensors(ha) {
  paintDoorRows(document.getElementById("haSensorTable"), ha, false);
}

function paintOverviewDoors(ha) {
  paintDoorRows(document.getElementById("overviewDoorTable"), ha, true);
}

function paintCameraRows(tbody, frigate, compact = false) {
  if (!tbody) return;
  tbody.innerHTML = "";
  const cameras = (frigate && frigate.details && frigate.details.cameras) || [];
  const colSpan = compact ? 3 : 6;

  if (!frigate || !frigate.online) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">${frigate && frigate.error ? frigate.error : "Frigate is offline"}</td></tr>`;
    return;
  }
  if (!cameras.length) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" class="empty-state">No cameras reporting.</td></tr>`;
    return;
  }

  cameras.forEach((camera) => {
    const tr = document.createElement("tr");
    tr.innerHTML = compact
      ? `
      <td><strong>${camera.name}</strong></td>
      <td>${statusPillHtml(camera.online ? "online" : "offline", camera.online ? "ok" : "critical")}</td>
      <td>${statusPillHtml(camera.detectionEnabled ? "enabled" : "disabled", camera.detectionEnabled ? "ok" : "warn")}</td>
    `
      : `
      <td><strong>${camera.name}</strong></td>
      <td>${statusPillHtml(camera.online ? "online" : "offline", camera.online ? "ok" : "critical")}</td>
      <td>${camera.cameraFps != null ? Number(camera.cameraFps).toFixed(1) : "-"}</td>
      <td>${camera.detectionFps != null ? Number(camera.detectionFps).toFixed(1) : "-"}</td>
      <td>${statusPillHtml(camera.detectionEnabled ? "on" : "off", camera.detectionEnabled ? "ok" : "warn")}</td>
      <td>${statusPillHtml(camera.recording ? "on" : "off", camera.recording ? "ok" : "muted")}</td>
    `;
    tbody.appendChild(tr);
  });
}

function paintFrigateCameras(frigate) {
  paintCameraRows(document.getElementById("frigateCameraTable"), frigate, false);
}

function paintOverviewCameras(frigate) {
  // Compact camera table removed from layout; previews are primary.
}

function paintOverviewCameraPreviews(frigate) {
  const container = document.getElementById("overviewCameraPreviews");
  const meta = document.getElementById("overviewPreviewMeta");
  if (!container) return;

  const cameras = (frigate && frigate.details && frigate.details.cameras) || [];
  const signature = cameras
    .map((camera) => `${camera.name}:${camera.online}:${camera.detectionEnabled}:${camera.recording}`)
    .join("|");

  if (!frigate || !frigate.online) {
    stopPreviewRefresh();
    container.dataset.signature = "";
    container.innerHTML = `<p class="empty-state">${frigate && frigate.error ? frigate.error : "Frigate is offline"}</p>`;
    if (meta) meta.textContent = "Live previews unavailable";
    return;
  }
  if (!cameras.length) {
    stopPreviewRefresh();
    container.dataset.signature = "";
    container.innerHTML = `<p class="empty-state">No cameras configured.</p>`;
    if (meta) meta.textContent = "No cameras found";
    return;
  }

  if (meta) {
    meta.textContent = `${frigate.details.onlineCameraCount || 0}/${frigate.details.cameraCount || 0} cameras · refresh ${PREVIEW_REFRESH_MS / 1000}s`;
  }

  if (container.dataset.signature === signature && container.querySelector(".camera-tile")) {
    if (activePanel === "overview") startPreviewRefresh();
    return;
  }

  stopPreviewRefresh();
  container.dataset.signature = signature;
  container.innerHTML = "";
  container.className = "camera-grid";

  cameras.forEach((camera) => {
    const tile = document.createElement("article");
    tile.className = "camera-tile";
    tile.innerHTML = `
      <a class="camera-image" href="${camera.livePageUrl || frigate.dashboardUrl}" target="_blank" rel="noopener">
        <img
          data-camera-preview="${camera.name}"
          data-preview-base="${cameraPreviewUrl(camera)}"
          alt="${camera.name} preview"
          loading="lazy"
          crossorigin="use-credentials"
          onerror="this.classList.add('preview-error')"
          onload="this.classList.remove('preview-error')"
        />
      </a>
      <footer><strong>${camera.name}</strong><span>${camera.recording ? "REC" : camera.online ? "Live" : "offline"}</span></footer>
    `;
    container.appendChild(tile);
  });

  startPreviewRefresh();
}

function mediaUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${CORE_BASE_URL}${path}`;
}

function formatDetectionWhen(item) {
  const local = item.start_time_local || item.startTimeLocal;
  if (local) {
    const date = new Date(local);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    }
    return String(local).replace("T", " ").slice(0, 16);
  }
  if (item.start_time) {
    const date = new Date(Number(item.start_time) * 1000);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    }
  }
  return "—";
}

function paintRecordingBar(frigate, canControl) {
  const details = (frigate && frigate.details) || {};
  const bridge = details.bridge || {};
  const schedule = details.schedule || {};
  const recording = Boolean(details.allRecording);
  const recordingCount = details.recordingEnabledCount || 0;
  const windowLabel = schedule.window ? `Night window ${schedule.window}` : "Schedule unknown";
  const zone = schedule.timezone ? ` · ${schedule.timezone}` : "";
  const inWindow = schedule.active ? " · currently in window" : "";
  const meta = !bridge.online
    ? bridge.error || "HCC Bridge offline — recording controls unavailable"
    : `${windowLabel}${zone}${inWindow}`;
  const stateLabel = recording ? "recording" : "idle";
  const stateTone = recording ? "ok" : "muted";

  [
    ["overviewRecordingMeta", meta],
    ["frigateRecordingMeta", meta],
  ].forEach(([id, text]) => setText(id, text));

  ["overviewRecordingState", "frigateRecordingState"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = `status-pill ${stateTone}`;
    el.textContent = recording ? `ON · ${recordingCount}` : "OFF";
    el.title = stateLabel;
  });

  document.querySelectorAll("[data-recording]").forEach((button) => {
    button.disabled = recordingPending || !bridge.online || !canControl;
    button.classList.toggle("disabled", button.disabled);
    if (!canControl) button.title = "Sign in with operator access to change recording";
    else if (!bridge.online) button.title = "HCC Bridge offline";
    else button.title = "";
  });
}

function paintDetections(containerId, metaId, frigate) {
  const container = document.getElementById(containerId);
  const meta = document.getElementById(metaId);
  if (!container) return;
  const items = (frigate && frigate.details && frigate.details.latestDetections) || [];
  if (meta) meta.textContent = items.length ? `${items.length} recent` : "No recent alerts";
  if (!frigate || !frigate.online) {
    container.innerHTML = `<p class="empty-state">${frigate && frigate.error ? frigate.error : "Frigate is offline"}</p>`;
    return;
  }
  if (!items.length) {
    container.innerHTML = `<p class="empty-state">No detections yet.</p>`;
    return;
  }
  container.innerHTML = items
    .map((item) => {
      const objects = (item.objects || []).join(", ") || item.label || "object";
      const thumb = mediaUrl(item.thumbnailUrl || item.thumbnail_url);
      const snapshot = mediaUrl(item.snapshotUrl || item.snapshot_url || thumb);
      const clip = mediaUrl(item.clipUrl || item.clip_url);
      const review = item.review_url || item.reviewUrl || (frigate && frigate.dashboardUrl) || "#";
      return `<article class="detection-card">
        <a class="detection-thumb" href="${snapshot}" target="_blank" rel="noopener" title="${item.camera || ""}">
          <img src="${thumb}" alt="${objects} on ${item.camera || "camera"}" loading="lazy" />
        </a>
        <footer>
          <strong>${item.camera || "Camera"}</strong>
          <span>${objects} · ${formatDetectionWhen(item)}</span>
          <div class="detection-links">
            ${clip ? `<a href="${clip}" target="_blank" rel="noopener">Clip</a>` : ""}
            <a href="${review}" target="_blank" rel="noopener">Review</a>
          </div>
        </footer>
      </article>`;
    })
    .join("");
}

async function setRecordingEnabled(enabled) {
  if (recordingPending) return;
  recordingPending = true;
  paintRecordingBar(serviceById("frigate"), true);
  const errorLabel = document.getElementById("errorLabel");
  try {
    securityPayload = await apiFetch("/api/v1/integrations/frigate/recording", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera: "all", enabled }),
    });
    await paintSecurityPage();
    if (errorLabel) errorLabel.textContent = "";
  } catch (err) {
    if (errorLabel) errorLabel.textContent = err.message || "Recording control failed";
  } finally {
    recordingPending = false;
    paintRecordingBar(serviceById("frigate"), canControlRecording(recordingControlUser));
  }
}

function wireRecordingButtons() {
  document.querySelectorAll("[data-recording]").forEach((button) => {
    if (button.dataset.wired) return;
    button.dataset.wired = "1";
    button.addEventListener("click", () => {
      const enabled = button.dataset.recording === "on";
      setRecordingEnabled(enabled);
    });
  });
}

async function paintSecurityPage() {
  const frigate = serviceById("frigate");
  const ha = serviceById("home-assistant");
  const user = await ensureRecordingAuth();
  const canControl = canControlRecording(user);
  paintSecuritySummary();
  paintSecurityCards();
  paintOverviewPlatforms(frigate, ha);
  paintOverviewCameraPreviews(frigate);
  paintOverviewCameras(frigate);
  paintOverviewDoors(ha);
  paintFrigateCameras(frigate);
  paintHaSensors(ha);
  paintIntegrationLinks();
  paintRecordingBar(frigate, canControl);
  paintDetections("overviewDetections", "overviewDetectionMeta", frigate);
  paintDetections("frigateDetections", "frigateDetectionMeta", frigate);
}

function paintOverviewPlatforms(frigate, ha) {
  const haMeta = document.getElementById("overviewHaMeta");
  if (haMeta && ha) {
    const details = ha.details || {};
    haMeta.textContent = `${ha.host} · ${details.sensorOnlineCount || 0}/${details.sensorCount || 0} door sensors`;
  }
  const totals = securityPayload.totals || {};
  const openDoors = ((ha && ha.details && ha.details.sensors) || []).filter((s) => s.state === "Open").length;
  if (openDoors > 0) {
    setStatusPill("securityPageStatus", `${openDoors} door open`, "critical");
  } else if ((totals.offlineCount || 0) > 0) {
    setStatusPill("securityPageStatus", `${totals.offlineCount} offline`, "warn");
  } else {
    setStatusPill("securityPageStatus", "nominal", "ok");
  }
}

function stopPreviewRefresh() {
  if (previewRefreshTimer) {
    clearInterval(previewRefreshTimer);
    previewRefreshTimer = null;
  }
}

function cameraPreviewUrl(camera) {
  const path =
    camera.previewUrl ||
    `/api/v1/integrations/frigate/camera/${encodeURIComponent(camera.name)}/latest.jpg`;
  return `${CORE_BASE_URL}${path}`;
}

function refreshPreviewImages() {
  const cacheBust = Date.now();
  document.querySelectorAll("img[data-camera-preview]").forEach((img) => {
    const base = img.dataset.previewBase;
    if (!base) return;
    img.classList.remove("preview-error");
    img.src = `${base}?t=${cacheBust}`;
  });
}

function startPreviewRefresh() {
  stopPreviewRefresh();
  if (activePanel !== "overview") return;
  refreshPreviewImages();
  previewRefreshTimer = setInterval(refreshPreviewImages, PREVIEW_REFRESH_MS);
}

function paintIntegrationLinks() {
  const frigate = serviceById("frigate");
  const ha = serviceById("home-assistant");
  if (frigate) {
    ["frigateOpenLink", "frigateEmbedLink"].forEach((id) => {
      const link = document.getElementById(id);
      if (link) link.href = frigate.dashboardUrl;
    });
    const frame = document.getElementById("frigateFrame");
    if (frame) frame.src = frigate.dashboardUrl;
  }
  if (ha) {
    ["haOpenLink", "haPrimaryLink"].forEach((id) => {
      const link = document.getElementById(id);
      if (link) link.href = ha.dashboardUrl;
    });
    setText("haHostLabel", ha.host);
  }
}

async function refreshSecurity() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    securityPayload = await apiFetch(SECURITY_ENDPOINT);
    await paintSecurityPage();
    errorLabel.textContent = "";
    return Number(securityPayload.refreshSeconds || 60);
  } catch (err) {
    errorLabel.textContent = `Security fetch failed: ${err.message}`;
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  initAppPage("security");
  paintSecuritySubNav(activePanel);
  showSecurityPanel(activePanel);
  wireRecordingButtons();
  while (true) {
    const waitSec = await refreshSecurity();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
