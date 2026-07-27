const PREVIEW_REFRESH_MS = 2500;

const GLANCE_IDS = {
  weatherHero: "weatherHero",
  weatherDaily: "weatherDaily",
  weatherLocation: "weatherLocation",
  weatherTemp: "weatherTemp",
  weatherCondition: "weatherCondition",
  weatherFeels: "weatherFeels",
  weatherWind: "weatherWind",
  weatherHumidity: "weatherHumidity",
  weatherUv: "weatherUv",
  weatherUpdated: "weatherUpdated",
  weatherIcon: "weatherIcon",
  securityStatus: "dashSecurityStatus",
  securityMeta: "dashSecurityMeta",
  doorList: "overviewDoorList",
  doorSummary: "dashDoorSummary",
  cameraPreviews: "overviewCameraPreviews",
  cameraSummary: "dashCameraSummary",
};

let previewRefreshTimer = null;
let cameraPreviewSignature = "";
let activeCameraContainerId = GLANCE_IDS.cameraPreviews;

function haService(securityPayload) {
  return (securityPayload.services || []).find((service) => service.id === "home-assistant");
}

function frigateService(securityPayload) {
  return (securityPayload.services || []).find((service) => service.id === "frigate");
}

function doorRowClass(sensor) {
  if (sensor.state === "Open") return "critical";
  if (sensor.status !== "online") return "warn";
  return "";
}

function doorStateClass(sensor) {
  if (sensor.state === "Open") return "";
  if (sensor.status !== "online") return "warn";
  return "ok";
}

function weatherIconSvg(conditionClass) {
  const svg = (body) =>
    `<svg viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
  const cloud =
    '<path d="M17 45h31a9 9 0 0 0 1.2-17.9A14 14 0 0 0 23 24.5 10.5 10.5 0 0 0 17 45Z" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
  const icons = {
    clear: svg(
      '<circle cx="32" cy="32" r="10" stroke="currentColor" stroke-width="3"/><g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M32 8v7"/><path d="M32 49v7"/><path d="M8 32h7"/><path d="M49 32h7"/><path d="m15 15 5 5"/><path d="m44 44 5 5"/><path d="m49 15-5 5"/><path d="m20 44-5 5"/></g>',
    ),
    "night-clear": svg(
      '<path d="M48.5 43.5A20 20 0 0 1 24 15a20.5 20.5 0 1 0 24.5 28.5Z" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="m43 14 .8 2.2L46 17l-2.2.8L43 20l-.8-2.2L40 17l2.2-.8L43 14Z" fill="currentColor"/><circle cx="51" cy="27" r="1.5" fill="currentColor"/>',
    ),
    "partly-cloudy": svg(
      '<circle cx="24" cy="23" r="8" stroke="currentColor" stroke-width="3"/><path d="M24 9v4M10 23h4m3-10-3-3m20 6 3-3" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>' +
        cloud,
    ),
    overcast: svg(
      '<path d="M11 38h27a8 8 0 0 0 .8-16A12 12 0 0 0 16 20.5 9 9 0 0 0 11 38Z" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/>' +
        '<path d="M23 50h28a8 8 0 0 0 .9-15.9A11.5 11.5 0 0 0 30 32.5 9 9 0 0 0 23 50Z" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    fog: svg(
      cloud +
        '<g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M13 51h29"/><path d="M24 57h27"/></g>',
    ),
    drizzle: svg(
      cloud +
        '<g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="m24 51-1 3"/><path d="m34 51-1 3"/><path d="m44 51-1 3"/></g>',
    ),
    rain: svg(
      cloud +
        '<g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="m23 51-2 5"/><path d="m34 51-2 5"/><path d="m45 51-2 5"/></g>',
    ),
    snow: svg(
      cloud +
        '<g stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M25 51v6m-3-3h6m-5-2 4 4m0-4-4 4"/><path d="M42 51v6m-3-3h6m-5-2 4 4m0-4-4 4"/></g>',
    ),
    storm: svg(
      cloud +
        '<path d="m35 48-5 9h7l-3 5 11-12h-7l3-5" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    wind: svg(
      '<g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M9 23h31c6 0 6-9 0-9-3 0-5 2-5 4"/><path d="M9 32h42c7 0 7 10 0 10-3 0-5-2-5-4"/><path d="M9 41h25"/></g>',
    ),
  };
  if (conditionClass === "windy") return icons.wind;
  return icons[conditionClass] || icons.overcast;
}

function formatWeatherUpdated(isoValue) {
  if (!isoValue) return "-";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "-";
  return `Updated ${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function cameraPreviewUrl(camera) {
  const path =
    camera.previewUrl || `/api/v1/integrations/frigate/camera/${encodeURIComponent(camera.name)}/latest.jpg`;
  return `${CORE_BASE_URL}${path}`;
}

function stopPreviewRefresh() {
  if (previewRefreshTimer) {
    clearInterval(previewRefreshTimer);
    previewRefreshTimer = null;
  }
}

function refreshPreviewImages() {
  const cacheBust = Date.now();
  const container = document.getElementById(activeCameraContainerId);
  if (!container) return;
  container.querySelectorAll("img[data-preview-base]").forEach((img) => {
    img.src = `${img.dataset.previewBase}?t=${cacheBust}`;
  });
}

function startPreviewRefresh() {
  stopPreviewRefresh();
  refreshPreviewImages();
  previewRefreshTimer = setInterval(refreshPreviewImages, PREVIEW_REFRESH_MS);
}

function configureGlance(ids = {}) {
  const merged = { ...GLANCE_IDS, ...ids };
  activeCameraContainerId = merged.cameraPreviews;
  return merged;
}

function paintDoorSensors(securityPayload, ids) {
  const container = document.getElementById(ids.doorList);
  const summary = document.getElementById(ids.doorSummary);
  if (!container) return;

  const ha = haService(securityPayload);
  const sensors = [...((ha && ha.details && ha.details.sensors) || [])].sort((a, b) => {
    const rank = (s) => (s.state === "Open" ? 0 : s.status !== "online" ? 1 : 2);
    return rank(a) - rank(b);
  });

  if (!ha || !ha.online) {
    container.innerHTML = `<p class="empty-state">${ha && ha.error ? ha.error : "Home Assistant offline"}</p>`;
    if (summary) summary.textContent = "offline";
    return;
  }
  if (!ha.details.sensorsConfigured) {
    container.innerHTML = `<p class="empty-state">Door sensor token not configured.</p>`;
    if (summary) summary.textContent = "not configured";
    return;
  }
  if (!sensors.length) {
    container.innerHTML = `<p class="empty-state">No door sensors found.</p>`;
    if (summary) summary.textContent = "0 sensors";
    return;
  }

  const openCount = sensors.filter((sensor) => sensor.state === "Open").length;
  const onlineCount = sensors.filter((sensor) => sensor.status === "online").length;
  if (summary) {
    summary.textContent = `${onlineCount}/${sensors.length} reporting${openCount ? ` · ${openCount} open` : ""}`;
  }

  container.innerHTML = "";
  sensors.forEach((sensor) => {
    const row = document.createElement("article");
    row.className = `door-row ${doorRowClass(sensor)}`.trim();
    const label = sensor.state === "Open" ? "OPEN" : sensor.state;
    row.innerHTML = `
      <span class="door-state ${doorStateClass(sensor)}" aria-hidden="true"></span>
      <div><h4>${sensor.name}</h4><p>${sensor.state} · ${sensor.status}</p></div>
      <strong>${label}</strong>
    `;
    container.appendChild(row);
  });
}

function paintCameraPreviews(securityPayload, ids) {
  const container = document.getElementById(ids.cameraPreviews);
  const summary = document.getElementById(ids.cameraSummary);
  if (!container) return;

  const frigate = frigateService(securityPayload);
  const cameras = (frigate && frigate.details && frigate.details.cameras) || [];
  const signature = cameras.map((camera) => `${camera.name}:${camera.online}:${camera.status}`).join("|");

  if (!frigate || !frigate.online) {
    stopPreviewRefresh();
    cameraPreviewSignature = "";
    container.innerHTML = `<p class="empty-state">${frigate && frigate.error ? frigate.error : "Frigate offline"}</p>`;
    if (summary) summary.textContent = "offline";
    return;
  }
  if (!cameras.length) {
    stopPreviewRefresh();
    cameraPreviewSignature = "";
    container.innerHTML = `<p class="empty-state">No cameras configured.</p>`;
    if (summary) summary.textContent = "0 cameras";
    return;
  }

  if (summary) {
    summary.textContent = `${frigate.details.onlineCameraCount || 0}/${frigate.details.cameraCount || 0} online`;
  }

  if (signature === cameraPreviewSignature && container.querySelector(".camera-tile")) {
    startPreviewRefresh();
    return;
  }

  stopPreviewRefresh();
  cameraPreviewSignature = signature;
  container.innerHTML = "";
  container.className = container.className.includes("camera-grid") ? container.className : `${container.className} camera-grid`.trim();

  cameras.forEach((camera) => {
    const tile = document.createElement("article");
    tile.className = "camera-tile";
    tile.innerHTML = `
      <a class="camera-image" href="${camera.livePageUrl || frigate.dashboardUrl || "#"}" target="_blank" rel="noopener" title="${camera.name}">
        <img
          data-preview-base="${cameraPreviewUrl(camera)}"
          alt="${camera.name} preview"
          loading="lazy"
          crossorigin="use-credentials"
          onerror="this.classList.add('preview-error')"
          onload="this.classList.remove('preview-error')"
        />
      </a>
      <footer>
        <strong>${camera.name}</strong>
        <span class="${camera.online ? "" : "offline"}">${camera.online ? "Live" : "offline"}</span>
      </footer>
    `;
    container.appendChild(tile);
  });

  startPreviewRefresh();
}

function paintSecurityGlance(securityPayload, ids = GLANCE_IDS) {
  const totals = (securityPayload && securityPayload.totals) || {};
  const offline = Number(totals.offlineCount || 0);
  const openDoors = ((haService(securityPayload)?.details?.sensors) || []).filter((s) => s.state === "Open").length;

  if (ids.securityStatus) {
    if (openDoors > 0) {
      setStatusPill(ids.securityStatus, `${openDoors} door open`, "critical");
    } else if (offline > 0) {
      setStatusPill(ids.securityStatus, `${offline} offline`, "warn");
    } else if ((totals.serviceCount || 0) === 0) {
      setStatusPill(ids.securityStatus, "not configured", "critical");
    } else {
      setStatusPill(ids.securityStatus, "nominal", "ok");
    }
  }

  if (ids.securityMeta) {
    setText(
      ids.securityMeta,
      `${totals.cameraCount || 0} camera(s) · ${totals.sensorCount || 0} door sensor(s) · Frigate + Home Assistant`,
    );
  }

  paintDoorSensors(securityPayload, ids);
  paintCameraPreviews(securityPayload, ids);
}

function paintWeather(payload, ids = GLANCE_IDS, options = {}) {
  const compact = Boolean(options.compact);
  const hero = document.getElementById(ids.weatherHero);
  const daily = document.getElementById(ids.weatherDaily);
  if (!hero || !daily) return;

  if (!payload || (payload.error && !payload.current)) {
    hero.dataset.condition = "overcast";
    setText(ids.weatherLocation, payload?.location?.label || "Weather unavailable");
    setText(ids.weatherCondition, payload?.error || "Unable to load forecast");
    daily.innerHTML = `<p class="empty-state">${payload?.error || "Weather unavailable"}</p>`;
    return;
  }

  const current = payload.current || {};
  const conditionClass = current.conditionClass || "overcast";
  hero.dataset.condition = conditionClass;

  const location = payload.location || {};
  setText(ids.weatherLocation, location.label || "Local forecast");
  setText(ids.weatherTemp, current.temperatureF != null ? String(current.temperatureF) : "--");
  setText(ids.weatherCondition, current.condition || "-");
  setText(ids.weatherFeels, current.feelsLikeF != null ? `${current.feelsLikeF}°` : "-");
  setText(
    ids.weatherWind,
    current.windMph != null ? `${current.windMph} mph ${current.windDirection || ""}`.trim() : "-",
  );
  const windValue = document.getElementById(ids.weatherWind);
  const windLabel = windValue?.parentElement?.querySelector("span");
  if (windLabel) windLabel.innerHTML = `${weatherIconSvg("wind")}Wind`;
  setText(ids.weatherHumidity, current.humidity != null ? `${current.humidity}%` : "-");
  setText(ids.weatherUv, current.uvIndex != null ? String(current.uvIndex) : "-");
  setText(ids.weatherUpdated, formatWeatherUpdated(payload.generatedAt));

  const icon = document.getElementById(ids.weatherIcon);
  if (icon) icon.innerHTML = weatherIconSvg(conditionClass);

  const rows = payload.daily || [];
  if (!rows.length) {
    daily.innerHTML = `<p class="empty-state">No forecast data</p>`;
    return;
  }

  daily.innerHTML = "";
  daily.classList.toggle("weather-daily--compact", compact);
  rows.forEach((day) => {
    const card = document.createElement("article");
    card.className = `weather-day${day.isToday ? " is-today" : ""}${compact ? " weather-day--compact" : ""}`;
    const precip =
      day.precipProbabilityMax != null
        ? `${day.precipProbabilityMax}%`
        : day.precipIn != null
          ? `${day.precipIn}"`
          : "Dry";
    if (compact) {
      card.innerHTML = `
        <div class="weather-day-name">
          ${day.isToday ? '<span class="weather-day-today">Today</span>' : ""}
          <span>${day.dayLabel || day.date}</span>
        </div>
        <div class="weather-day-icon">${weatherIconSvg(day.conditionClass || "overcast")}</div>
        <div class="weather-day-temps">
          <span class="weather-day-high">${day.highF != null ? `${day.highF}°` : "-"}</span>
          <span class="weather-day-low">${day.lowF != null ? `${day.lowF}°` : "-"}</span>
        </div>
        <div class="weather-day-meta"><div>${precip}</div></div>
      `;
    } else {
      card.innerHTML = `
        <div class="weather-day-name">
          ${day.isToday ? '<span class="weather-day-today">Today</span>' : ""}
          <span>${day.dayLabel || day.date}</span>
        </div>
        <div class="weather-day-icon">${weatherIconSvg(day.conditionClass || "overcast")}</div>
        <div class="weather-day-condition">${day.condition || "-"}</div>
        <div class="weather-day-temps">
          <span class="weather-day-high">${day.highF != null ? `${day.highF}°` : "-"}</span>
          <span class="weather-day-low">${day.lowF != null ? `${day.lowF}°` : "-"}</span>
        </div>
        <div class="weather-day-meta">
          <div><strong>Precip</strong> ${precip}</div>
          <div><strong>Wind</strong> ${day.windMphMax != null ? `${day.windMphMax} mph ${day.windDirection || ""}`.trim() : "-"}</div>
          <div><strong>UV</strong> ${day.uvIndexMax != null ? day.uvIndexMax : "-"}</div>
          ${
            day.isToday && day.sunrise && day.sunset
              ? `<div><strong>Sun</strong> ${day.sunrise} – ${day.sunset}</div>`
              : ""
          }
        </div>
      `;
    }
    daily.appendChild(card);
  });
}
