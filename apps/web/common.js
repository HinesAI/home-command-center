function resolveCoreBaseUrl() {
  if (window.HCC_CORE_BASE_URL) return window.HCC_CORE_BASE_URL;
  const protocol = window.location.protocol;
  const host = window.location.hostname;
  // Canonical hostname: UI + API share origin via Caddy (/api → core)
  if (host === "hcc.example.local") {
    return window.location.origin;
  }
  const knownCoreHosts = new Set(["192.168.1.10", "example.local"]);
  if (knownCoreHosts.has(host) || host === "192.168.1.10") {
    return `${protocol}//192.168.1.10:18080`;
  }
  return `${protocol}//${host}:18080`;
}

const CORE_BASE_URL = resolveCoreBaseUrl();
const AUTH_LOGIN_PATH = "./login.html";
const HCC_VERSION_ENDPOINT = "/api/v1/system/version";
const DEFAULT_PRODUCT_NAME = "Home Command Center";
const DEFAULT_PRODUCT_SHORT_NAME = "HCC";

let hccBranding = {
  product: DEFAULT_PRODUCT_NAME,
  shortName: DEFAULT_PRODUCT_SHORT_NAME,
};

const HCC_ASCII_WIDE = `#     #                           #####                                               #####
#     # # #    # ######  ####    #     #  ####  #    # #    #   ##   #    # #####    #     # ###### #    # ##### ###### #####
#     # # ##   # #      #        #       #    # ##  ## ##  ##  #  #  ##   # #    #   #       #      ##   #   #   #      #    #
####### # # #  # #####   ####    #       #    # # ## # # ## # #    # # #  # #    #   #       #####  # #  #   #   #####  #    #
#     # # #  # # #           #   #       #    # #    # #    # ###### #  # # #    #   #       #      #  # #   #   #      #####
#     # # #   ## #      #    #   #     # #    # #    # #    # #    # #   ## #    #   #     # #      #   ##   #   #      #   #
#     # # #    # ######  ####     #####   ####  #    # #    # #    # #    # #####     #####  ###### #    #   #   ###### #    #`;

const HCC_ASCII_NARROW = ` _   _ _                    ____
| | | (_)_ __   ___  ___   / ___|___  _ __ ___  _ __ ___   __ _ _ __   __| |
| |_| | | '_ \\ / _ \\/ __| | |   / _ \\| '_ \` _ \\| '_ \` _ \\ / _\` | '_ \\ / _\` |
|  _  | | | | |  __/\\__ \\ | |__| (_) | | | | | | | | | | | (_| | | | | (_| |
|_| |_|_|_| |_|\\___||___/  \\____\\___/|_| |_| |_|_| |_| |_|\\__,_|_| |_|\\__,_|

  ____           _
 / ___|___ _ __ | |_ ___ _ __
| |   / _ \\ '_ \\| __/ _ \\ '__|
| |__|  __/ | | | ||  __/ |
 \\____\\___|_| |_|\\__\\___|_|`;

function loginPageUrl(nextPath = "./index.html") {
  return `${AUTH_LOGIN_PATH}?next=${encodeURIComponent(nextPath)}`;
}

function brandAsciiHtml(options = {}) {
  const href = options.href || "./index.html";
  const product = options.product || hccBranding.product || DEFAULT_PRODUCT_NAME;
  return `<a class="brand brand--ascii" href="${href}" aria-label="${product}">
  <pre class="brand-ascii brand-ascii--wide" aria-hidden="true">${HCC_ASCII_WIDE}</pre>
  <pre class="brand-ascii brand-ascii--narrow" aria-hidden="true">${HCC_ASCII_NARROW}</pre>
</a>`;
}

async function loadBranding() {
  try {
    const release = await apiFetch(HCC_VERSION_ENDPOINT);
    hccBranding = {
      product: release.product || DEFAULT_PRODUCT_NAME,
      shortName: release.shortName || DEFAULT_PRODUCT_SHORT_NAME,
    };
  } catch (_err) {
    hccBranding = {
      product: DEFAULT_PRODUCT_NAME,
      shortName: DEFAULT_PRODUCT_SHORT_NAME,
    };
  }
  return hccBranding;
}

function paintTextBrands() {
  const product = hccBranding.product || DEFAULT_PRODUCT_NAME;
  document.querySelectorAll(".brand strong").forEach((node) => {
    node.textContent = product;
  });
  document.querySelectorAll(".brand[aria-label]").forEach((node) => {
    if (!node.classList.contains("brand--ascii")) {
      node.setAttribute("aria-label", product);
    }
  });
  document.querySelectorAll("#gateAsciiWide[aria-label]").forEach((node) => {
    node.setAttribute("aria-label", product);
  });
}

function ensureBrandFonts() {
  if (document.getElementById("hccBrandFonts")) return;
  const link = document.createElement("link");
  link.id = "hccBrandFonts";
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Share+Tech+Mono&display=swap";
  document.head.appendChild(link);
}

function paintBrand(options = {}) {
  ensureBrandFonts();
  const mount = document.getElementById("appBrand");
  if (mount) {
    mount.outerHTML = brandAsciiHtml(options);
    return;
  }
  const existing = document.querySelector("header.topbar > a.brand, .kiosk-header .brand");
  if (existing) {
    existing.outerHTML = brandAsciiHtml(options);
    return;
  }
  const topbar = document.querySelector("header.topbar");
  if (topbar) {
    topbar.insertAdjacentHTML("afterbegin", brandAsciiHtml(options));
  }
}

let loginOverlayNext = "./index.html";

function ensureLoginOverlay() {
  if (document.getElementById("loginOverlay")) return;
  const overlay = document.createElement("div");
  overlay.id = "loginOverlay";
  overlay.className = "login-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="login-overlay-backdrop" data-login-dismiss></div>
    <div class="login-overlay-panel" role="dialog" aria-modal="true" aria-labelledby="loginOverlayTitle">
      <div class="login-term-bar">
        <span class="login-term-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="login-term-title" id="loginOverlayTitle">sign in</span>
        <button type="button" class="login-overlay-close" data-login-dismiss aria-label="Close">×</button>
      </div>
      <form id="loginOverlayForm" class="login-overlay-form">
        <label>
          Username
          <input id="loginOverlayUsername" name="username" autocomplete="username" required />
        </label>
        <label>
          Password
          <input id="loginOverlayPassword" name="password" type="password" autocomplete="current-password" required />
        </label>
        <button type="submit">Enter</button>
        <div id="loginOverlayError" class="admin-status error" role="alert"></div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (event) => {
    if (event.target.closest("[data-login-dismiss]")) closeLoginOverlay();
  });
  document.getElementById("loginOverlayForm").addEventListener("submit", handleLoginOverlaySubmit);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.hidden) closeLoginOverlay();
  });
}

function openLoginOverlay(options = {}) {
  ensureLoginOverlay();
  loginOverlayNext =
    options.next ||
    new URLSearchParams(window.location.search).get("next") ||
    window.location.pathname + window.location.search ||
    "./index.html";
  const overlay = document.getElementById("loginOverlay");
  const error = document.getElementById("loginOverlayError");
  const userInput = document.getElementById("loginOverlayUsername");
  const passInput = document.getElementById("loginOverlayPassword");
  if (error) error.textContent = "";
  if (passInput) passInput.value = "";
  overlay.hidden = false;
  document.body.classList.add("login-overlay-open");
  window.setTimeout(() => userInput?.focus(), 30);
}

function closeLoginOverlay() {
  const overlay = document.getElementById("loginOverlay");
  if (!overlay) return;
  overlay.hidden = true;
  document.body.classList.remove("login-overlay-open");
}

async function handleLoginOverlaySubmit(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const username = document.getElementById("loginOverlayUsername").value.trim();
  const password = document.getElementById("loginOverlayPassword").value;
  const errorLabel = document.getElementById("loginOverlayError");
  errorLabel.textContent = "";
  if (button) {
    button.disabled = true;
    button.dataset.label = button.textContent;
    button.textContent = "Authenticating…";
  }
  try {
    await login(username, password);
    const next = loginOverlayNext || "./index.html";
    window.location.href = next.startsWith("/") ? next : next;
  } catch (err) {
    errorLabel.textContent = err.message;
    if (button) {
      button.disabled = false;
      button.textContent = button.dataset.label || "Enter";
    }
  }
}

function bindAuthGates(root = document) {
  root.querySelectorAll("[data-requires-auth]").forEach((el) => {
    if (el.dataset.authBound === "true") return;
    el.dataset.authBound = "true";
    el.addEventListener("click", (event) => {
      event.preventDefault();
      const next = el.getAttribute("href") || el.dataset.next || "./index.html";
      openLoginOverlay({ next });
    });
  });
}

async function apiFetch(path, options = {}) {
  const config = {
    credentials: "include",
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  };
  const res = await fetch(`${CORE_BASE_URL}${path}`, config);
  let body = {};
  try {
    body = await res.json();
  } catch (_err) {
    body = {};
  }
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    const err = new Error(body.error || "authentication required");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const err = new Error(body.error || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = body;
    err.reason = body.reason;
    throw err;
  }
  return body;
}

async function login(username, password) {
  return apiFetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

async function logout() {
  try {
    await apiFetch("/api/v1/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (_err) {
    // ignore
  }
  window.location.href = AUTH_LOGIN_PATH;
}

async function fetchCurrentUser() {
  return apiFetch("/api/v1/auth/me");
}

async function ensureAuth(options = {}) {
  const { redirect = true } = options;
  try {
    const body = await fetchCurrentUser();
    if (body.user) {
      paintAuthUser(body.user);
    }
    return body.user;
  } catch (err) {
    if (redirect && err.status === 401) {
      window.location.href = loginPageUrl(window.location.pathname + window.location.search);
      return null;
    }
    throw err;
  }
}

function paintAuthUser(user) {
  const label = document.getElementById("authUserLabel");
  if (!label || !user) return;
  label.textContent = user.displayName || user.username;
  label.title = `${user.displayName || user.username} (${user.role})`;
  const adminLink = document.getElementById("adminNavLink");
  if (adminLink) {
    const canAdmin = user.isLocalAdmin || user.role === "maintainer" || user.role === "deployer";
    adminLink.style.display = canAdmin ? "" : "none";
    adminLink.classList.toggle("active", window.location.pathname.endsWith("/admin.html"));
  }
}

function bindLogoutButton() {
  const button = document.getElementById("logoutBtn");
  if (!button) return;
  button.addEventListener("click", () => logout());
}

const APP_NAV_LINKS = [
  { id: "overview", href: "./index.html", label: "Overview" },
  { id: "kiosk", href: "./kiosk.html", label: "Kiosk" },
  { id: "kiosk-compact", href: "./kiosk-compact.html", label: "Kiosk Mini" },
  { id: "devices", href: "./devices.html", label: "Enrolled Devices" },
  { id: "vms", href: "./vms.html", label: "Virtual Machines" },
  { id: "containers", href: "./containers.html", label: "Docker Containers" },
  { id: "security", href: "./security.html", label: "Security" },
  { id: "climate", href: "./climate.html", label: "Climate Controls" },
];

function paintAppNav(active) {
  const nav = document.getElementById("appNav");
  if (!nav) return;
  nav.innerHTML = APP_NAV_LINKS.map(
    (link) => `<a href="${link.href}" class="${active === link.id ? "active" : ""}">${link.label}</a>`,
  ).join("");
}

function paintSubNav(containerId, links, activeId, options = {}) {
  const nav = document.getElementById(containerId);
  if (!nav) return;
  const useButtons = Boolean(options.useButtons);
  nav.innerHTML = links
    .map((link) => {
      const activeClass = activeId === link.id ? "active" : "";
      if (useButtons) {
        return `<button type="button" class="${activeClass}" data-panel="${link.id}">${link.label}</button>`;
      }
      return `<a href="${link.href}" class="${activeClass}">${link.label}</a>`;
    })
    .join("");
}

function statusPillTone(statusOrClass) {
  const value = String(statusOrClass || "").toLowerCase();
  if (value === "running" || value === "online" || value === "ok" || value === "status-running") return "ok";
  if (
    value === "starting" ||
    value === "warn" ||
    value === "stale" ||
    value === "paused" ||
    value === "status-starting"
  ) {
    return "warn";
  }
  if (value === "stopped" || value === "offline" || value === "critical" || value === "status-stopped") {
    return "critical";
  }
  return "";
}

function statusPillHtml(label, tone = "") {
  const cls = tone ? ` status-pill ${tone}` : " status-pill";
  return `<span class="${cls.trim()}">${label}</span>`;
}

function setStatusPill(elementId, label, tone) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = label;
  el.className = `status-pill ${tone || ""}`.trim();
}

function initAppPage(activeNavId) {
  return loadBranding().then(() => {
    paintBrand();
    paintTextBrands();
    bindLogoutButton();
    paintAppNav(activeNavId);
    startWallClock();
    paintAppVersion();
  });
}

async function paintAppVersion() {
  const footer = document.querySelector(".page-footer");
  if (!footer) return;
  let label = document.getElementById("hccVersionLabel");
  if (!label) {
    label = document.createElement("span");
    label.id = "hccVersionLabel";
    label.className = "hcc-version-label";
    footer.appendChild(label);
  }
  try {
    const release = await apiFetch(HCC_VERSION_ENDPOINT);
    const product = release.product || DEFAULT_PRODUCT_NAME;
    const version = release.version || "0.0.0-dev";
    label.textContent = `${product} · v${version}`;
    label.title = `${release.releaseChannel || "stable"} release`;
  } catch (_err) {
    label.textContent = DEFAULT_PRODUCT_NAME;
  }
}

let wallClockTimer = null;
function startWallClock() {
  const clock = document.getElementById("wallClock");
  const timeEl = document.getElementById("wallClockTime");
  const dateEl = document.getElementById("wallClockDate");
  if (!clock && !timeEl) return;
  const tick = () => {
    const now = new Date();
    const timeText = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const dateText = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    if (timeEl) {
      timeEl.textContent = timeText;
    } else if (clock) {
      clock.textContent = timeText;
    }
    if (dateEl) dateEl.textContent = dateText;
    if (clock) clock.dateTime = now.toISOString();
  };
  tick();
  if (wallClockTimer) clearInterval(wallClockTimer);
  wallClockTimer = setInterval(tick, 1000);
}

function updateCommandStrip({ headline, tone = "ok", incidents = 0, online = "-", total = "-", freshness = "-", lastRefresh = "-" }) {
  const dot = document.getElementById("commandStatusDot");
  const title = document.getElementById("commandHeadline");
  const incidentsEl = document.getElementById("commandIncidents");
  const servicesEl = document.getElementById("commandServices");
  const freshnessEl = document.getElementById("commandFreshness");
  const refreshEl = document.getElementById("lastRefresh");
  if (dot) dot.className = `status-dot ${tone === "critical" ? "critical" : ""}`.trim();
  if (title) title.textContent = headline || "All hosts online";
  if (incidentsEl) incidentsEl.textContent = String(incidents);
  if (servicesEl) servicesEl.textContent = `${online} / ${total}`;
  if (freshnessEl) freshnessEl.textContent = freshness;
  if (refreshEl) refreshEl.textContent = lastRefresh;
}

function devicesPageUrl(category) {
  if (category === "servers") return "./devices-servers.html";
  if (category === "clients") return "./devices-clients.html";
  return "./devices.html";
}

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = Number(bytes || 0);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatUptime(sec) {
  const total = Number(sec || 0);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function statusClass(status) {
  if (status === "running") return "status-running";
  if (status === "starting") return "status-starting";
  return "status-stopped";
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function row(cells) {
  const tr = document.createElement("tr");
  cells.forEach((value) => {
    const td = document.createElement("td");
    if (value instanceof Node) {
      td.appendChild(value);
    } else {
      td.textContent = String(value);
    }
    tr.appendChild(td);
  });
  return tr;
}

function osText(node) {
  const os = (node && node.os) || {};
  return [os.name, os.version].filter(Boolean).join(" ") || "-";
}

function serverPageUrl(nodeId) {
  return `./server.html?nodeId=${encodeURIComponent(nodeId)}`;
}

function queryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function barClass(percent) {
  if (percent >= 90) return "bad";
  if (percent >= 75) return "warn";
  return "";
}

function setGauge(elementId, percent, label, subText) {
  const root = document.getElementById(elementId);
  if (!root) return;
  const valueEl = root.querySelector(".noc-kpi-value");
  const barEl = root.querySelector(".noc-bar");
  const barFill = root.querySelector(".noc-bar > span");
  const subEl = root.querySelector(".noc-kpi-sub");
  if (valueEl) valueEl.textContent = label || pct(percent);
  if (subEl) subEl.textContent = subText || "";
  if (barEl && barFill) {
    barEl.className = `noc-bar ${barClass(percent)}`.trim();
    barFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }
}

function formatCpuTopology(cpu, resources) {
  const logical = Number(
    (cpu && (cpu.logicalCpus || cpu.cores || cpu.threads)) ||
    (resources && resources.cpuLogical) ||
    0,
  );
  const physical = Number(
    (cpu && cpu.physicalCores) ||
    (resources && resources.cpuPhysical) ||
    logical,
  );
  if (logical && physical && logical !== physical) {
    return `${physical} cores / ${logical} threads`;
  }
  if (logical) return `${logical} core${logical === 1 ? "" : "s"}`;
  return "-";
}

function formatLoad(resources) {
  const load = resources || {};
  const one = Number(load.load1 || 0);
  const five = Number(load.load5 || 0);
  const fifteen = Number(load.load15 || 0);
  if (!one && !five && !fifteen) return "-";
  return `${one.toFixed(2)} / ${five.toFixed(2)} / ${fifteen.toFixed(2)}`;
}

function formatLoadLabel(resources, platform) {
  const load = resources || {};
  if (platform === "windows") {
    const queue = Number(load.queueLength || load.load1 || 0);
    return queue ? `queue ${queue.toFixed(0)}` : "load n/a";
  }
  return `load ${formatLoad(load)}`;
}

function hostSections(snapshot) {
  const caps = (snapshot && snapshot.capabilities) || {};
  const sections = caps.sections || {};
  const hostRole = (snapshot && snapshot.node && snapshot.node.hostRole) || caps.hostRole || "unknown";
  if (Object.keys(sections).length) {
    return {
      services: sections.services === true,
      containers: sections.containers === true,
      vms: sections.vms === true,
    };
  }
  if (hostRole === "proxmox") {
    return { services: false, containers: false, vms: true };
  }
  if (hostRole === "windows-client") {
    return { services: true, containers: false, vms: false };
  }
  if (hostRole === "windows-server") {
    return { services: true, containers: false, vms: false };
  }
  const focus = ((snapshot && snapshot.workloads) || {}).focus || [];
  return {
    services: focus.includes("services"),
    containers: focus.includes("containers"),
    vms: false,
  };
}

function vmActionAllowed(actionId, status) {
  const state = String(status || "unknown").toLowerCase();
  const isRunning = state === "running";
  const isStopped = state === "stopped";
  const isPaused = state === "paused";

  if (actionId === "vm.start") {
    return isStopped || isPaused || (!isRunning && !isPaused);
  }
  if (actionId === "vm.stop") {
    return isRunning || isPaused;
  }
  if (actionId === "vm.shutdown" || actionId === "vm.reboot") {
    return isRunning;
  }
  return false;
}

function containerActionAllowed(actionId, status) {
  const normalized = String(status || "stopped").toLowerCase();
  if (actionId === "container.start") {
    return normalized === "stopped" || normalized === "created";
  }
  if (actionId === "container.stop") {
    return normalized === "running" || normalized === "restarting" || normalized === "paused";
  }
  if (actionId === "container.restart") {
    return normalized === "running" || normalized === "restarting" || normalized === "paused";
  }
  return false;
}

function serviceActionAllowed(actionId, status) {
  const normalized = String(status || "stopped").toLowerCase();
  if (actionId === "service.start") {
    return normalized === "stopped" || normalized === "stop pending";
  }
  if (actionId === "service.stop") {
    return normalized === "running" || normalized === "start pending";
  }
  if (actionId === "service.restart") {
    return normalized === "running" || normalized === "start pending";
  }
  return false;
}

function nodeTypeLabel(hardware) {
  if (!hardware) return "Unknown";
  if (hardware.isContainer) return "Container";
  if (hardware.isVirtualMachine) return "Virtual Machine";
  if (hardware.isPhysical) return "Physical Host";
  return hardware.virtualizationType || "Unknown";
}

function zfsHealthClass(health) {
  const value = String(health || "").toLowerCase();
  if (value === "online") return "status-running";
  if (value.includes("degrad")) return "status-starting";
  return "status-stopped";
}

async function submitAction(nodeId, actionId, target = null, params = {}, dangerous = false) {
  if (dangerous) {
    const label = target ? `${actionId} ${target}` : actionId;
    if (!window.confirm(`Confirm dangerous action: ${label}?`)) {
      return { ok: false, cancelled: true };
    }
  }
  const res = await apiFetch("/api/v1/actions/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nodeId,
      actionId,
      target,
      params,
    }),
  });
  return res;
}
