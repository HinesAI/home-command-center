const SECURITY_ENDPOINT = "/api/v1/integrations/security";
const WEATHER_ENDPOINT = "/api/v1/integrations/weather";

const KIOSK_GLANCE_IDS = configureGlance({
  weatherHero: "kioskWeatherHero",
  weatherDaily: "kioskWeatherDaily",
  weatherLocation: "kioskWeatherLocation",
  weatherTemp: "kioskWeatherTemp",
  weatherCondition: "kioskWeatherCondition",
  weatherFeels: "kioskWeatherFeels",
  weatherWind: "kioskWeatherWind",
  weatherHumidity: "kioskWeatherHumidity",
  weatherUv: "kioskWeatherUv",
  weatherUpdated: "kioskWeatherUpdated",
  weatherIcon: "kioskWeatherIcon",
  securityStatus: "kioskSecurityStatus",
  securityMeta: "kioskSecurityMeta",
  doorList: "kioskDoorList",
  doorSummary: "kioskDoorSummary",
  cameraPreviews: "kioskCameraPreviews",
  cameraSummary: "kioskCameraSummary",
});

async function handleKioskClimateUpdated(result, err) {
  const user = await ensureClimateAuth();
  if (err) return;
  if (!result) return;
  paintClimate(result, {
    containerId: "kioskClimateCards",
    compact: true,
    interactive: canControlClimate(user),
    onUpdated: handleKioskClimateUpdated,
  });
}

async function refreshKiosk() {
  const errorLabel = document.getElementById("kioskErrorLabel");
  const errors = [];
  let refreshSeconds = 120;

  const results = await Promise.allSettled([
    apiFetch(SECURITY_ENDPOINT),
    apiFetch(WEATHER_ENDPOINT),
    apiFetch(CLIMATE_ENDPOINT),
  ]);
  const [securityResult, weatherResult, climateResult] = results;
  const securityPayload = securityResult.status === "fulfilled" ? securityResult.value : null;

  if (securityPayload) {
    paintSecurityGlance(securityPayload, KIOSK_GLANCE_IDS);
    refreshSeconds = Math.min(refreshSeconds, Number(securityPayload.refreshSeconds || 60));
  } else {
    errors.push(`Security: ${securityResult.reason.message}`);
    setStatusPill("kioskSecurityStatus", "error", "critical");
    stopPreviewRefresh();
  }

  if (weatherResult.status === "fulfilled") {
    paintWeather(weatherResult.value, KIOSK_GLANCE_IDS, { compact: true });
    refreshSeconds = Math.min(refreshSeconds, Number(weatherResult.value.refreshSeconds || 900));
  } else {
    paintWeather({ error: weatherResult.reason?.message || "Weather fetch failed" }, KIOSK_GLANCE_IDS, {
      compact: true,
    });
    errors.push(`Weather: ${weatherResult.reason.message}`);
  }

  if (climateResult.status === "fulfilled") {
    const user = await ensureClimateAuth();
    paintClimate(climateResult.value, {
      containerId: "kioskClimateCards",
      compact: true,
      interactive: canControlClimate(user),
      onUpdated: handleKioskClimateUpdated,
    });
    refreshSeconds = Math.min(refreshSeconds, Number(climateResult.value.refreshSeconds || 30));
  } else {
    paintClimate({ error: climateResult.reason?.message || "Climate fetch failed" }, {
      containerId: "kioskClimateCards",
      compact: true,
    });
    errors.push(`Climate: ${climateResult.reason.message}`);
  }

  if (errorLabel) errorLabel.textContent = errors.join(" | ");
  return refreshSeconds;
}

async function loop() {
  paintBrand({
    href: document.body.classList.contains("kiosk-compact") ? "./kiosk-compact.html" : "./kiosk.html",
  });
  const user = await ensureAuth({ redirect: false }).catch(() => null);
  startWallClock();
  if (!user) {
    document.body.classList.add("kiosk-guest");
  }
  while (true) {
    const waitSec = await refreshKiosk();
    await new Promise((resolve) => setTimeout(resolve, Math.max(5, waitSec) * 1000));
  }
}

loop();
