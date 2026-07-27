const CLIMATE_PAGE_ENDPOINT = "/api/v1/integrations/climate";

function paintClimatePageSummary(payload) {
  const totals = payload.totals || {};
  const thermostats = payload.thermostats || [];
  const primary = thermostats[0];
  setText("climateThermostatCount", String(totals.thermostatCount || 0));
  setText("climateOnlineCount", String(totals.onlineCount || 0));
  setText("climateActiveCount", String(totals.activeCount || 0));
  setText(
    "climatePrimarySummary",
    primary
      ? `${primary.currentTemperatureF ?? "—"}° / ${primary.targetTemperatureF ?? "—"}° · ${primary.hvacModeLabel}`
      : "—",
  );
  const haLink = document.getElementById("climateHaLink");
  if (haLink && payload.haUrl) {
    haLink.href = payload.haUrl;
  }
  const timeLabel = document.getElementById("climateTimeLabel");
  if (timeLabel && payload.generatedAt) {
    timeLabel.textContent = `Updated: ${new Date(payload.generatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  }
}

async function handleClimateUpdated(result, err) {
  const errorLabel = document.getElementById("errorLabel");
  const user = await ensureClimateAuth();
  if (err) {
    if (errorLabel) errorLabel.textContent = `Climate update failed: ${err.message}`;
    return;
  }
  if (errorLabel) errorLabel.textContent = "";
  if (!result) return;
  paintClimate(result, {
    containerId: "climateCards",
    statusId: "climatePageStatus",
    metaId: "climatePageMeta",
    interactive: canControlClimate(user),
    onUpdated: handleClimateUpdated,
  });
  paintClimatePageSummary(result);
}

async function refreshClimatePage() {
  const errorLabel = document.getElementById("errorLabel");
  try {
    const payload = await apiFetch(CLIMATE_PAGE_ENDPOINT);
    const user = await ensureClimateAuth();
    paintClimate(payload, {
      containerId: "climateCards",
      statusId: "climatePageStatus",
      metaId: "climatePageMeta",
      interactive: canControlClimate(user),
      onUpdated: handleClimateUpdated,
    });
    paintClimatePageSummary(payload);
    if (errorLabel && payload.error) {
      errorLabel.textContent = payload.error;
    } else if (errorLabel) {
      errorLabel.textContent = "";
    }
    return Number(payload.refreshSeconds || 30);
  } catch (err) {
    if (errorLabel) errorLabel.textContent = `Climate fetch failed: ${err.message}`;
    paintClimate({ error: err.message }, { containerId: "climateCards", statusId: "climatePageStatus" });
    return 30;
  }
}

async function loop() {
  await ensureAuth();
  await ensureClimateAuth();
  initAppPage("climate");
  while (true) {
    const waitSec = await refreshClimatePage();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
