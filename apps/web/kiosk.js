const SECURITY_ENDPOINT = "/api/v1/integrations/security";
const WEATHER_ENDPOINT = "/api/v1/integrations/weather";
const FAMILY_ENDPOINT = "/api/v1/integrations/family";

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
  doorList: "kioskDoorList",
  doorSummary: "kioskDoorSummary",
  cameraPreviews: "kioskCameraPreviews",
  cameraSummary: "kioskCameraSummary",
});

let activeView = "home";
let familyBoard = null;
let calCursor = new Date();
let selectedDayKey = dayKey(new Date());
let swipeStartX = 0;
let swipeStartY = 0;

function dayKey(date) {
  const d = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseEventDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatAgendaWhen(event) {
  if (event.allDay) return "All day";
  const d = parseEventDate(event.start);
  if (!d) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function eventTouchesDay(event, key) {
  const start = parseEventDate(event.start);
  if (!start) return false;
  const startKey = dayKey(start);
  const end = parseEventDate(event.end);
  if (!end) return key === startKey;

  // CalDAV / iCal: all-day DTEND is exclusive; timed events ending at 00:00
  // also mean "through end of previous day" — don't paint the next square.
  const exclusiveEnd =
    Boolean(event.allDay) ||
    (end.getHours() === 0 && end.getMinutes() === 0 && end.getSeconds() === 0 && end.getMilliseconds() === 0);

  if (exclusiveEnd) {
    const endKey = dayKey(end);
    if (endKey <= startKey) return key === startKey;
    return key >= startKey && key < endKey;
  }
  return key >= startKey && key <= dayKey(end);
}

function eventsForDay(events, key) {
  return (events || []).filter((event) => eventTouchesDay(event, key));
}

/** Compact in-cell label; full title appears in agenda when the day is tapped. */
function formatPillLabel(event) {
  const title = String(event.title || "Event").trim() || "Event";
  if (event.allDay) return title;
  const d = parseEventDate(event.start);
  if (!d) return title;
  let hour = d.getHours();
  const minute = d.getMinutes();
  const ap = hour >= 12 ? "p" : "a";
  hour = hour % 12 || 12;
  const time = minute ? `${hour}:${String(minute).padStart(2, "0")}${ap}` : `${hour}${ap}`;
  return `${time} ${title}`;
}

function formatPillTime(event) {
  if (event.allDay) return "All day";
  const d = parseEventDate(event.start);
  if (!d) return "";
  let hour = d.getHours();
  const minute = d.getMinutes();
  const ap = hour >= 12 ? "p" : "a";
  hour = hour % 12 || 12;
  return minute ? `${hour}:${String(minute).padStart(2, "0")}${ap}` : `${hour}${ap}`;
}

function weeksInMonthGrid(year, month) {
  const first = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startPad = first.getDay();
  return Math.ceil((startPad + daysInMonth) / 7);
}

function setKioskView(view) {
  const next = view === "family" ? "family" : "home";
  activeView = next;
  document.querySelectorAll(".kiosk-page").forEach((page) => {
    const match = page.dataset.view === next;
    page.classList.toggle("is-active", match);
    page.hidden = !match;
  });
  document.querySelectorAll(".kiosk-view-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === next);
  });
  const url = new URL(window.location.href);
  if (next === "home") url.searchParams.delete("view");
  else url.searchParams.set("view", next);
  history.replaceState({}, "", url);
  if (next === "family") {
    paintFamilyView();
    refreshFamily();
  }
}

function paintMonthGrid(board) {
  const grid = document.getElementById("kioskCalGrid");
  const title = document.getElementById("kioskCalTitle");
  if (!grid || !title) return;

  const year = calCursor.getFullYear();
  const month = calCursor.getMonth();
  title.textContent = new Date(year, month, 1).toLocaleString(undefined, {
    month: "long",
    year: "numeric",
  });

  const first = new Date(year, month, 1);
  const startPad = first.getDay();
  const start = new Date(year, month, 1 - startPad);
  const weeks = weeksInMonthGrid(year, month);
  const cellCount = weeks * 7;
  const todayKey = dayKey(new Date());
  const events = board?.events || board?.upcoming || [];

  grid.style.setProperty("--kiosk-cal-weeks", String(weeks));

  const cells = [];
  for (let i = 0; i < cellCount; i += 1) {
    const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const key = dayKey(date);
    const inMonth = date.getMonth() === month;
    const dayEvents = eventsForDay(events, key);
    const shown = dayEvents.slice(0, 3);
    const more = dayEvents.length - shown.length;
    const hasEvents = dayEvents.length > 0;
    cells.push(`
      <button type="button" class="kiosk-cal-day${inMonth ? "" : " is-outside"}${
        key === todayKey ? " is-today" : ""
      }${key === selectedDayKey ? " is-selected" : ""}${hasEvents ? " has-events" : ""}" data-day="${key}">
        <span class="kiosk-cal-day-num">${date.getDate()}</span>
        <div class="kiosk-cal-events">
          ${shown
            .map((event) => {
              const kind =
                event.kind === "reminder" ? "reminder" : event.allDay ? "allday" : "timed";
              return `<span class="kiosk-cal-pill kiosk-cal-pill--${kind}" title="${escapeHtml(
                event.title || "Event",
              )}">${escapeHtml(formatPillLabel(event))}</span>`;
            })
            .join("")}
          ${more > 0 ? `<span class="kiosk-cal-more">+${more} more</span>` : ""}
        </div>
      </button>
    `);
  }
  grid.innerHTML = cells.join("");
}

function paintAgenda(board) {
  const list = document.getElementById("kioskAgendaList");
  const title = document.getElementById("kioskAgendaTitle");
  const count = document.getElementById("kioskAgendaCount");
  if (!list || !title) return;

  const selected = parseEventDate(`${selectedDayKey}T12:00:00`);
  const label = selected
    ? selected.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })
    : "Day";
  const dayEvents = eventsForDay(board?.events || board?.upcoming || [], selectedDayKey);
  const isToday = dayKey(new Date()) === selectedDayKey;
  title.textContent = isToday
    ? `Today · ${selected.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}`
    : label;
  if (count) count.textContent = dayEvents.length ? `${dayEvents.length}` : "Clear";

  if (!dayEvents.length) {
    list.innerHTML = `<p class="empty-state">Nothing scheduled</p>`;
    return;
  }
  list.innerHTML = dayEvents
    .map((event) => {
      const isReminder = event.kind === "reminder";
      const timeLabel = isReminder ? "Reminder" : formatPillTime(event);
      const loc = event.location ? String(event.location) : "";
      const note = isReminder && event.notes ? String(event.notes) : "";
      const sub = [loc, note].filter(Boolean).join(" · ");
      return `<article class="kiosk-family-item${isReminder ? " is-reminder" : ""}">
        <time class="kiosk-family-when" datetime="${escapeHtml(event.start || "")}">${escapeHtml(timeLabel)}</time>
        <div class="kiosk-family-item-body">
          <strong>${escapeHtml(event.title || "Event")}</strong>
          ${sub ? `<span>${escapeHtml(sub)}</span>` : ""}
        </div>
      </article>`;
    })
    .join("");
}

function paintFamilyView() {
  if (!familyBoard) {
    setStatusPill("kioskFamilyStatus", "loading", "warn");
    return;
  }
  const source = familyBoard.source === "caldav" ? "iCal" : "local";
  const tone = familyBoard.caldav?.ok === false ? "warn" : "ok";
  setStatusPill("kioskFamilyStatus", source, tone);
  paintMonthGrid(familyBoard);
  paintAgenda(familyBoard);
}

async function refreshFamily() {
  try {
    familyBoard = await apiFetch(FAMILY_ENDPOINT);
    if (activeView === "family") paintFamilyView();
    return "";
  } catch (err) {
    setStatusPill("kioskFamilyStatus", "error", "critical");
    const chores = document.getElementById("kioskChoresList");
    if (chores) chores.innerHTML = `<p class="empty-state">${escapeHtml(err.message || "Family unavailable")}</p>`;
    return `Family: ${err.message || err}`;
  }
}

async function handleKioskClimateUpdated(result, err) {
  const user = await ensureClimateAuth();
  if (err) return;
  if (!result) return;
  paintClimate(result, {
    containerId: "kioskClimateCards",
    statusId: "kioskClimateStatus",
    compact: true,
    interactive: canControlClimate(user),
    onUpdated: handleKioskClimateUpdated,
  });
}

async function refreshHome() {
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
      statusId: "kioskClimateStatus",
      compact: true,
      interactive: canControlClimate(user),
      onUpdated: handleKioskClimateUpdated,
    });
    refreshSeconds = Math.min(refreshSeconds, Number(climateResult.value.refreshSeconds || 30));
  } else {
    paintClimate(
      { error: climateResult.reason?.message || "Climate fetch failed" },
      {
        containerId: "kioskClimateCards",
        statusId: "kioskClimateStatus",
        compact: true,
      },
    );
    errors.push(`Climate: ${climateResult.reason.message}`);
  }

  return { refreshSeconds, errors };
}

function wireKioskChrome() {
  document.querySelectorAll(".kiosk-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => setKioskView(btn.dataset.view));
  });

  document.getElementById("kioskCalPrev")?.addEventListener("click", () => {
    calCursor = new Date(calCursor.getFullYear(), calCursor.getMonth() - 1, 1);
    paintFamilyView();
  });
  document.getElementById("kioskCalNext")?.addEventListener("click", () => {
    calCursor = new Date(calCursor.getFullYear(), calCursor.getMonth() + 1, 1);
    paintFamilyView();
  });

  document.getElementById("kioskCalGrid")?.addEventListener("click", (event) => {
    const day = event.target.closest("[data-day]");
    if (!day) return;
    selectedDayKey = day.dataset.day;
    paintFamilyView();
  });

  const pages = document.getElementById("kioskPages");
  if (!pages) return;
  pages.addEventListener(
    "touchstart",
    (event) => {
      const touch = event.changedTouches[0];
      swipeStartX = touch.clientX;
      swipeStartY = touch.clientY;
    },
    { passive: true },
  );
  pages.addEventListener(
    "touchend",
    (event) => {
      const touch = event.changedTouches[0];
      const dx = touch.clientX - swipeStartX;
      const dy = touch.clientY - swipeStartY;
      if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.4) return;
      if (dx < 0 && activeView === "home") setKioskView("family");
      if (dx > 0 && activeView === "family") setKioskView("home");
    },
    { passive: true },
  );
}

async function loop() {
  paintBrand({ href: "./kiosk.html" });
  const user = await ensureAuth({ redirect: false }).catch(() => null);
  startWallClock();
  if (!user) document.body.classList.add("kiosk-guest");

  wireKioskChrome();
  const initial = new URLSearchParams(window.location.search).get("view");
  setKioskView(initial === "family" ? "family" : "home");

  let homeWait = 30;
  let familyWait = 20;
  let homeElapsed = 0;
  let familyElapsed = 0;

  while (true) {
    const errorLabel = document.getElementById("kioskErrorLabel");
    const errors = [];

    if (homeElapsed <= 0) {
      const home = await refreshHome();
      homeWait = Math.max(5, Number(home.refreshSeconds || 30));
      homeElapsed = homeWait;
      errors.push(...home.errors);
    }
    if (familyElapsed <= 0) {
      const familyError = await refreshFamily();
      familyWait = Math.max(10, Number(familyBoard?.refreshSeconds || 20));
      familyElapsed = familyWait;
      if (familyError) errors.push(familyError);
    }

    if (errorLabel) errorLabel.textContent = errors.join(" | ");

    await new Promise((resolve) => setTimeout(resolve, 1000));
    homeElapsed -= 1;
    familyElapsed -= 1;
  }
}

loop();
