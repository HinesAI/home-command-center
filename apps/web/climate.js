const CLIMATE_ENDPOINT = "/api/v1/integrations/climate";
const CLIMATE_SET_ENDPOINT = "/api/v1/integrations/climate/set";

let climateControlUser = null;
let climatePending = false;

function canControlClimate(user) {
  if (!user) return false;
  if (user.isLocalAdmin) return true;
  const rank = { observer: 0, operator: 1, maintainer: 2, deployer: 3 };
  return (rank[user.role] || 0) >= 1;
}

async function ensureClimateAuth() {
  if (climateControlUser) return climateControlUser;
  try {
    const body = await fetchCurrentUser();
    climateControlUser = body.user || null;
  } catch (_err) {
    climateControlUser = null;
  }
  return climateControlUser;
}

function formatClimateControlError(err) {
  const message = String(err?.message || err || "Climate control failed");
  if (message.toLowerCase().includes("authentication required")) {
    return "Session expired — sign in again to control the thermostat.";
  }
  if (message.includes("Sensi integration")) {
    return message;
  }
  if (message.toLowerCase().includes("remote end closed") || message.toLowerCase().includes("climate control failed")) {
    return "Home Assistant rejected the thermostat command. Reload the Sensi integration in HA and check logs.";
  }
  return message;
}

function showClimateCardError(card, message) {
  if (!card || !message) return;
  let note = card.querySelector(".climate-error-note");
  if (!note) {
    note = document.createElement("p");
    note.className = "climate-error-note";
    card.appendChild(note);
  }
  note.textContent = message;
  window.clearTimeout(note._hideTimer);
  note._hideTimer = window.setTimeout(() => note.remove(), 10000);
}

async function setClimateControl(payload) {
  if (climatePending) return null;
  climatePending = true;
  try {
    return await apiFetch(CLIMATE_SET_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } finally {
    climatePending = false;
  }
}

function climateModeTone(mode, action) {
  const normalized = String(mode || "").toLowerCase();
  const active = String(action || "").toLowerCase();
  if (normalized === "off") return "muted";
  if (active === "heating") return "warn";
  if (active === "cooling") return "ok";
  return "warn";
}

function climateStatusLine(thermostat) {
  const parts = [thermostat.hvacActionLabel || "—"];
  if (thermostat.fanMode) {
    parts.push(`Fan ${thermostat.fanMode}`);
  }
  if (thermostat.humidity != null) {
    parts.push(`${thermostat.humidity}% humidity`);
  }
  if (thermostat.currentTemperatureF != null) {
    parts.push(`${thermostat.currentTemperatureF}° inside`);
  }
  return parts.join(" · ");
}

function fanModeLabel(mode) {
  if (!mode) return mode;
  if (mode.toLowerCase() === "on") return "On";
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

function thermostatCardHtml(thermostat, options = {}) {
  const compact = Boolean(options.compact);
  const glance = Boolean(options.glance);
  const interactive = Boolean(options.interactive);
  const disabled = !interactive || climatePending ? " disabled" : "";
  const target = thermostat.targetTemperatureF;
  const min = thermostat.minTempF ?? 45;
  const max = thermostat.maxTempF ?? 95;
  const modeButtons = (thermostat.hvacModes || []).map((mode) => {
    const active = mode === thermostat.hvacMode ? " is-active" : "";
    const label = mode === "heat_cool" ? "Auto" : mode.charAt(0).toUpperCase() + mode.slice(1);
    return `<button type="button" class="climate-mode-btn${active}" data-action="mode" data-mode="${mode}"${disabled}>${label}</button>`;
  }).join("");

  const fanButtons = (thermostat.fanModes || []).map((mode) => {
    const active = String(mode).toLowerCase() === String(thermostat.fanMode || "").toLowerCase() ? " is-active" : "";
    return `<button type="button" class="climate-fan-btn${active}" data-action="fan" data-fan="${mode}"${disabled}>${fanModeLabel(mode)}</button>`;
  }).join("");

  const setpointBlock =
    target != null
      ? `
    <div class="climate-setpoint-wrap">
      <button type="button" class="climate-step" data-action="temp-down" aria-label="Decrease temperature"${disabled}>−</button>
      <div class="climate-setpoint">
        <span class="climate-label">Set to</span>
        <strong class="climate-target">${target}°</strong>
      </div>
      <button type="button" class="climate-step" data-action="temp-up" aria-label="Increase temperature"${disabled}>+</button>
    </div>`
      : `<div class="climate-setpoint-wrap climate-setpoint-wrap--auto">
      <div class="climate-setpoint">
        <span class="climate-label">Auto range</span>
        <strong class="climate-target">${thermostat.targetTempLowF ?? "—"}° – ${thermostat.targetTempHighF ?? "—"}°</strong>
      </div>
    </div>`;

  return `
    <article
      class="climate-card${compact ? " climate-card--compact" : ""}${glance ? " climate-card--glance" : ""}"
      data-entity-id="${thermostat.entityId}"
      data-mode="${thermostat.hvacMode || "off"}"
      data-min="${min}"
      data-max="${max}"
      data-target="${target ?? ""}"
    >
      <header class="climate-card-head">
        <div>
          <h3>${thermostat.name}</h3>
          <p class="climate-status">${climateStatusLine(thermostat)}</p>
        </div>
        <span class="status-pill ${thermostat.online ? climateModeTone(thermostat.hvacMode, thermostat.hvacAction) : "critical"}">
          ${thermostat.online ? thermostat.hvacModeLabel : "Offline"}
        </span>
      </header>
      <div class="climate-temps">
        <div class="climate-room">
          <span class="climate-label">Inside</span>
          <strong class="climate-current">${thermostat.currentTemperatureF != null ? `${thermostat.currentTemperatureF}°` : "—"}</strong>
        </div>
        ${setpointBlock}
      </div>
      ${modeButtons ? `<div class="climate-mode-row" aria-label="HVAC mode">${modeButtons}</div>` : ""}
      ${fanButtons ? `<div class="climate-fan-row" aria-label="Fan mode"><span class="climate-row-label">Fan</span>${fanButtons}</div>` : ""}
      ${interactive ? "" : `<p class="climate-readonly-note">Sign in with operator access to change settings.</p>`}
    </article>
  `;
}

function bindClimateContainer(container, onUpdated) {
  if (!container || container.dataset.climateBound === "true") return;
  container.dataset.climateBound = "true";

  container.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled || climatePending) return;

    const card = button.closest(".climate-card");
    if (!card) return;
    const entityId = card.dataset.entityId;
    const min = Number(card.dataset.min || 45);
    const max = Number(card.dataset.max || 95);
    let target = card.dataset.target === "" ? null : Number(card.dataset.target);
    const action = button.dataset.action;
    let payload = { entityId };

    if (action === "mode") {
      payload.hvacMode = button.dataset.mode;
    } else if (action === "fan") {
      payload.fanMode = button.dataset.fan;
    } else if (action === "temp-up" || action === "temp-down") {
      if (target == null || Number.isNaN(target)) return;
      target += action === "temp-up" ? 1 : -1;
      target = Math.max(min, Math.min(max, target));
      payload.temperature = target;
    } else {
      return;
    }

    card.classList.add("is-busy");
    try {
      const result = await setClimateControl(payload);
      if (typeof onUpdated === "function") {
        onUpdated(result);
      }
    } catch (err) {
      if (err?.status === 401 && typeof openLoginOverlay === "function") {
        openLoginOverlay({ next: window.location.pathname + window.location.search || "./climate.html" });
      }
      showClimateCardError(card, formatClimateControlError(err));
      if (typeof onUpdated === "function") {
        onUpdated(null, err);
      }
    } finally {
      card.classList.remove("is-busy");
    }
  });
}

function paintClimate(payload, options = {}) {
  const containerId = options.containerId || "climateCards";
  const statusId = options.statusId || "climateStatus";
  const metaId = options.metaId || "climateMeta";
  const container = document.getElementById(containerId);
  if (!container) return;

  const user = options.user ?? climateControlUser;
  const interactive = options.interactive != null ? options.interactive : canControlClimate(user);
  const compact = Boolean(options.compact);
  const glance = Boolean(options.glance);

  if (!payload || payload.error) {
    if (statusId) setStatusPill(statusId, "offline", "critical");
    if (metaId) setText(metaId, payload?.error || "Climate unavailable");
    container.innerHTML = `<p class="empty-state">${payload?.error || "Unable to load thermostat"}</p>`;
    return;
  }

  if (!payload.configured) {
    if (statusId) setStatusPill(statusId, "not configured", "warn");
    if (metaId) setText(metaId, "Configure HCC_HA_TOKEN on core");
    container.innerHTML = `<p class="empty-state">Home Assistant token not configured.</p>`;
    return;
  }

  const thermostats = payload.thermostats || [];
  const totals = payload.totals || {};
  const active = totals.activeCount || 0;

  if (statusId) {
    if (!payload.haOnline) {
      setStatusPill(statusId, "HA offline", "critical");
    } else if (!thermostats.length) {
      setStatusPill(statusId, "no thermostats", "warn");
    } else if (active > 0) {
      setStatusPill(statusId, active === 1 ? "running" : `${active} active`, "ok");
    } else {
      setStatusPill(statusId, "idle", "ok");
    }
  }

  if (metaId) {
    const primary = thermostats[0];
    const summary = primary
      ? `${primary.currentTemperatureF ?? "—"}° inside · set ${primary.targetTemperatureF ?? "—"}° · ${primary.hvacModeLabel}`
      : "No climate entities found";
    setText(metaId, thermostats.length ? summary : "Add climate entities in Home Assistant");
  }

  if (!thermostats.length) {
    container.innerHTML = `<p class="empty-state">No thermostats found in Home Assistant.</p>`;
    return;
  }

  container.innerHTML = thermostats
    .map((thermostat) => thermostatCardHtml(thermostat, { compact, glance, interactive }))
    .join("");
  bindClimateContainer(container, options.onUpdated);
}
