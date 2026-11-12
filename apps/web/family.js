const FAMILY_ENDPOINT = "/api/v1/integrations/family";

let familyBoard = null;

function icsSubscribeUrl() {
  return `${CORE_BASE_URL}/api/v1/integrations/family/calendar.ics`;
}

function toLocalInputValue(isoOrLocal) {
  if (!isoOrLocal) return "";
  const d = new Date(isoOrLocal);
  if (Number.isNaN(d.getTime())) return String(isoOrLocal).slice(0, 16);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInputValue(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString();
}

function formatWhen(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function setError(msg) {
  const el = document.getElementById("errorLabel");
  if (el) el.textContent = msg || "";
}

function paintBoard(board) {
  familyBoard = board;
  const summary = board.summary || {};
  const events = board.upcoming || board.events || [];
  const chores = board.chores || [];
  const open = chores.filter((c) => !c.done);
  const done = chores.filter((c) => c.done);

  document.getElementById("statEvents").textContent = String(summary.upcomingEventCount ?? events.length);
  document.getElementById("statChores").textContent = String(summary.openChoreCount ?? open.length);
  document.getElementById("statDone").textContent = String(done.length);
  document.getElementById("familyUpdated").textContent = `Updated: ${board.updatedAt || board.generatedAt || "-"}`;
  setStatusPill("familyStatus", board.source === "caldav" ? "Calendar.app" : "local", board.caldav?.ok === false ? "warn" : "ok");
  document.getElementById("icsUrl").textContent = icsSubscribeUrl();

  const hint = document.getElementById("caldavHint");
  const localSection = document.getElementById("localEditSection");
  const eventForm = document.getElementById("eventForm");
  const choreForm = document.getElementById("choreForm");
  const serverEl = document.getElementById("caldavServer");
  if (serverEl) serverEl.textContent = "caldav.example.local";

  if (board.source === "caldav" && board.caldav?.ok !== false) {
    if (hint) {
      hint.textContent =
        "CalDAV connected. Add and remove events in Calendar.app; chores/reminders in Reminders (or the Chores calendar). This page is display-only.";
    }
    if (localSection) localSection.hidden = true;
  } else if (board.caldav?.enabled && board.caldav?.ok === false) {
    if (hint) {
      hint.textContent = `CalDAV configured but not reachable: ${board.caldav.error || "check server / calendar paths"}. Fix Admin → Family calendar, then manage from Calendar.app.`;
    }
    if (localSection) localSection.hidden = true;
  } else {
    if (hint) {
      hint.textContent =
        "CalDAV not connected yet. After deploy/scripts/init-caldav.sh, add the CalDAV account on each phone — day-to-day edits stay in Calendar.app / Reminders.";
    }
    if (localSection) localSection.hidden = false;
    if (eventForm) eventForm.hidden = false;
    if (choreForm) choreForm.hidden = false;
  }

  const eventList = document.getElementById("eventList");
  if (!events.length) {
    eventList.innerHTML = `<p class="empty-state">No upcoming events. Add one above.</p>`;
  } else {
    eventList.innerHTML = events
      .map(
        (event) => `<article class="family-item" data-id="${event.id}">
          <div>
            <h3>${escapeHtml(event.title || "Event")}</h3>
            <p>${escapeHtml(formatWhen(event.start))}${event.location ? " · " + escapeHtml(event.location) : ""}</p>
            ${event.notes ? `<p>${escapeHtml(event.notes)}</p>` : ""}
          </div>
          <div class="family-item-actions">
            <button type="button" data-action="delete-event">Remove</button>
          </div>
        </article>`,
      )
      .join("");
  }

  const choreList = document.getElementById("choreList");
  if (!chores.length) {
    choreList.innerHTML = `<p class="empty-state">No chores yet.</p>`;
  } else {
    choreList.innerHTML = chores
      .map(
        (chore) => `<article class="family-item ${chore.done ? "done" : ""}" data-id="${chore.id}">
          <div>
            <h3>${escapeHtml(chore.title || "Chore")}</h3>
            <p>${chore.assignee ? escapeHtml(chore.assignee) : "Unassigned"}${chore.due ? " · due " + escapeHtml(chore.due) : ""}</p>
            ${chore.notes ? `<p>${escapeHtml(chore.notes)}</p>` : ""}
          </div>
          <div class="family-item-actions">
            <button type="button" data-action="toggle-chore">${chore.done ? "Reopen" : "Done"}</button>
            <button type="button" data-action="delete-chore">Remove</button>
          </div>
        </article>`,
      )
      .join("");
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function refreshFamily() {
  try {
    const board = await apiFetch(FAMILY_ENDPOINT);
    paintBoard(board);
    setError("");
  } catch (err) {
    setStatusPill("familyStatus", "error", "critical");
    setError(err.message || String(err));
  }
}

async function postFamily(path, body) {
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function wireForms() {
  document.getElementById("eventForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const data = new FormData(form);
    try {
      const result = await postFamily(`${FAMILY_ENDPOINT}/events`, {
        title: data.get("title"),
        start: fromLocalInputValue(data.get("start")),
        end: data.get("end") ? fromLocalInputValue(data.get("end")) : null,
        location: data.get("location") || null,
        notes: data.get("notes") || null,
        allDay: data.get("allDay") === "on",
      });
      paintBoard(result.board);
      form.reset();
      setError("");
    } catch (err) {
      setError(err.message || String(err));
    }
  });

  document.getElementById("choreForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const data = new FormData(form);
    try {
      const result = await postFamily(`${FAMILY_ENDPOINT}/chores`, {
        title: data.get("title"),
        assignee: data.get("assignee") || null,
        due: data.get("due") || null,
        notes: data.get("notes") || null,
      });
      paintBoard(result.board);
      form.reset();
      setError("");
    } catch (err) {
      setError(err.message || String(err));
    }
  });

  document.getElementById("eventList").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const item = btn.closest("[data-id]");
    const id = item?.dataset.id;
    if (!id) return;
    try {
      const result = await postFamily(`${FAMILY_ENDPOINT}/events/${id}`, { action: "delete" });
      paintBoard(result.board);
    } catch (err) {
      setError(err.message || String(err));
    }
  });

  document.getElementById("choreList").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const item = btn.closest("[data-id]");
    const id = item?.dataset.id;
    if (!id) return;
    const chore = (familyBoard?.chores || []).find((c) => c.id === id);
    try {
      let result;
      if (btn.dataset.action === "delete-chore") {
        result = await postFamily(`${FAMILY_ENDPOINT}/chores/${id}`, { action: "delete" });
      } else {
        result = await postFamily(`${FAMILY_ENDPOINT}/chores/${id}`, { done: !chore?.done });
      }
      paintBoard(result.board);
    } catch (err) {
      setError(err.message || String(err));
    }
  });
}

async function loop() {
  await initAppPage("family");
  wireForms();
  while (true) {
    await refreshFamily();
    await new Promise((r) => setTimeout(r, 20000));
  }
}

loop();
