# HCC Dashboard — Frontend Design Brief

Hand this document to a designer (or Codex design pass). The output should be implementable by a coding agent into the existing static web app under `apps/web/`.

---

## 1. Product context

**Home Command Center** is a homelab / small-enterprise infrastructure dashboard. It aggregates telemetry from agents on Windows servers, Linux servers, Proxmox hypervisors, and Linux VMs, and exposes read-only monitoring plus allowlisted control actions (services, VMs, Docker containers).

**Primary user goal:** At a glance, know if the estate is healthy — especially **security (doors + cameras)** and **server health** — then drill into detail pages.

**Domain:** `EXAMPLE.LOCAL`  
**Typical deployment:** Web UI `:3000`, Core API `:18080` (e.g. `http://192.168.1.10:3000`)

---

## 2. Technical constraints (must preserve)

| Constraint | Detail |
|------------|--------|
| Stack | Vanilla HTML + CSS + JS (no React/Vue required today) |
| API | REST JSON from HCC Core; session cookie auth |
| CORS | Web origin talks to core on different port; `credentials: include` |
| Polling | Pages poll APIs every 60–120s; camera previews poll every 2.5s |
| No mock backend | Design against real API shapes below |
| Files | One HTML + one JS per major page; shared `common.js`, `styles.css`, `noc.css` |

Designer may propose a component library or design tokens file. Implementation should map cleanly onto existing file layout unless explicitly migrating stack.

---

## 3. Information architecture

```
Login (login.html)
└── Overview (index.html)          ← command center / home
├── Enrolled Devices (devices.html)
│   ├── All Servers (devices-servers.html)
│   └── All Clients (devices-clients.html)
├── Host Detail (server.html?nodeId=…)   ← per-node NOC view
├── Virtual Machines (vms.html)
├── Docker Containers (containers.html)
├── Security (security.html)
│   ├── sub: Overview | Frigate | Home Assistant
└── Admin (admin.html)             ← agent releases, inventory
```

**Global nav** (from `common.js` → `paintAppNav`):

| ID | Label | Route |
|----|-------|-------|
| overview | Overview | `./index.html` |
| devices | Enrolled Devices | `./devices.html` |
| vms | Virtual Machines | `./vms.html` |
| containers | Docker Containers | `./containers.html` |
| security | Security | `./security.html` |

Header right: auth user label, Admin link, Logout.

---

## 4. Page priorities (UX hierarchy)

### Tier 1 — Overview home (`index.html`)

**Order top → bottom:**

1. **Security (hero)** — highest priority  
   - Door sensor list: name, state (Open/Closed/Unavailable), online/offline  
   - Open doors must be visually alarming  
   - Camera preview grid: live JPEG snapshots (4 Frigate cameras today)  
   - Status pill: nominal / door open / service offline  
   - CTA: Open Security  

2. **Server Health (hero)**  
   - Fleet aggregate meters: avg CPU, memory use, storage use  
   - Compact server table: hostname (link), role, CPU%, mem%, storage%, online/stale  
   - Stale servers sort to top  
   - CTA: Open Server Fleet  

3. **Quick links row** (low visual weight)  
   - VMs: running / stopped counts → `vms.html`  
   - Docker Containers: running / host count → `containers.html`  
   - Clients: enrolled / stale → `devices-clients.html`  

### Tier 2 — Drill-down pages

Each page = summary strip + filterable table or cards + state-based action buttons.

| Page | Primary content | Actions |
|------|-----------------|---------|
| Devices | Card grid by host | Link to server detail |
| Server detail | Gauges, services, Docker, VMs (role-dependent), history | service/vm/container/host actions |
| VMs | All Proxmox VMs fleet-wide | start/stop/shutdown/reboot by VM state |
| Docker Containers | All containers on Linux Docker hosts | start/stop/restart by container state |
| Security | Frigate cameras, HA doors, platform cards, Frigate iframe tab | external links; previews on overview tab |

---

## 5. Design system (current tokens)

From `apps/web/styles.css`:

```css
--bg: #060b12
--panel: #111926
--panel-border: #1d2a3c
--text: #ecf2ff
--muted: #9bb0cc
--ok: #2ed47a      /* running / healthy */
--warn: #f5c344    /* attention */
--bad: #ff5b5b     /* stopped / open door / error */
```

**Status classes:** `status-running`, `status-starting`, `status-stopped`  
**Meter thresholds:** `<75%` ok, `75–89%` warn, `≥90%` bad (`barClass()` in common.js)

**Typography:** Inter / system sans  
**Theme:** Dark only today  
**Density:** Prefer scannable summaries; avoid wall-of-cards on overview

`noc.css` adds NOC-style gauges/tables for `server.html`.

---

## 6. Shared JS utilities (`common.js`)

Implementations must use these — do not reinvent:

| Function | Purpose |
|----------|---------|
| `apiFetch(path, options)` | Authenticated JSON fetch to core |
| `ensureAuth()` | Redirect to login if 401 |
| `paintAppNav(activeId)` | Top navigation |
| `submitAction(nodeId, actionId, target, params, dangerous)` | Queue agent action |
| `formatBytes`, `pct`, `formatUptime`, `statusClass`, `barClass` | Formatting |
| `serverPageUrl(nodeId)` | Link to host detail |
| `vmActionAllowed`, `containerActionAllowed`, `serviceActionAllowed` | Gate action buttons |
| `hostSections(snapshot)` | Which panels to show on server page |

**Core base URL:** `window.HCC_CORE_BASE_URL` or `{protocol}//{hostname}:18080`

---

## 7. API reference (frontend consumption)

All authenticated GETs unless noted. Responses include `generatedAt` and usually `refreshSeconds`.

### Fleet

| Endpoint | Used by | Key fields |
|----------|---------|------------|
| `GET /api/v1/fleet/overview?physicalOnly=false` | Overview, Devices | `totals`, `groups.servers`, `groups.clients`, `items[]` |
| `GET /api/v1/fleet/vms` | Overview, VMs | `totals`, `hosts[]`, `items[]` (VM rows) |
| `GET /api/v1/fleet/containers` | Overview, Docker page | `totals`, `hosts[]`, `items[]` (container rows) |
| `GET /api/v1/fleet/node?nodeId=` | Server detail | `snapshot`, `summary` |
| `GET /api/v1/fleet/node/history?nodeId=&limit=` | Server detail | time series CPU/mem/storage/net |
| `GET /api/v1/fleet/node/capabilities?nodeId=` | Server detail | allowed actions |

**Fleet item (server) shape:**

```json
{
  "nodeId": "appserver01",
  "hostname": "appserver01.example.local",
  "hostRole": "ubuntu-server",
  "deviceCategory": "server",
  "stale": false,
  "platform": "linux",
  "resources": {
    "cpuPercent": 12.4,
    "memoryPercent": 38.2,
    "storagePercent": 55.0,
    "memoryUsedBytes": 0,
    "memoryTotalBytes": 0
  },
  "uptimeSec": 86400,
  "ips": ["192.168.1.11"]
}
```

**VM item shape:**

```json
{
  "nodeId": "proxmox-01",
  "hostname": "Hypervisor01",
  "id": "100",
  "name": "Frigate",
  "type": "qemu",
  "status": "running",
  "memoryMb": 8096,
  "diskGb": 80,
  "osType": "l26",
  "hostStale": false,
  "actions": [{ "id": "vm.start", "scope": "vm", "label": "Start" }]
}
```

**Docker container item shape:**

```json
{
  "nodeId": "docker01",
  "hostname": "docker01",
  "name": "nextcloud-app-1",
  "image": "nextcloud:latest",
  "status": "running",
  "statusText": "Up 3 days",
  "cpuPercent": 0.8,
  "memoryUsedBytes": 116077363,
  "memoryLimitBytes": 0,
  "networkIo": "1MB / 2MB",
  "hostStale": false,
  "actions": [{ "id": "container.restart", "scope": "container" }]
}
```

### Security / integrations

| Endpoint | Used by |
|----------|---------|
| `GET /api/v1/integrations/security` | Overview, Security page |
| `GET /api/v1/integrations/frigate/camera/{name}/latest.jpg` | Camera previews (img + cookies) |

**Security response:**

```json
{
  "totals": {
    "serviceCount": 2,
    "onlineCount": 2,
    "offlineCount": 0,
    "cameraCount": 4,
    "sensorCount": 3
  },
  "services": [
    {
      "id": "frigate",
      "name": "Frigate NVR",
      "online": true,
      "host": "192.168.1.30:5000",
      "dashboardUrl": "http://192.168.1.30:5000",
      "details": {
        "cameraCount": 4,
        "onlineCameraCount": 4,
        "cameras": [
          {
            "name": "driveway",
            "online": true,
            "previewUrl": "/api/v1/integrations/frigate/camera/driveway/latest.jpg",
            "livePageUrl": "http://192.168.1.30:5000/live/driveway"
          }
        ]
      }
    },
    {
      "id": "home-assistant",
      "details": {
        "sensorsConfigured": true,
        "sensors": [
          {
            "name": "back-door",
            "state": "Closed",
            "status": "online",
            "stateClass": "status-running"
          }
        ]
      }
    }
  ]
}
```

### Actions

`POST /api/v1/actions/execute`

```json
{
  "nodeId": "docker01",
  "actionId": "container.restart",
  "target": "nextcloud-app-1",
  "params": {}
}
```

Returns `202` queued; agent runs on next heartbeat (~2 min). UI shows “queued” feedback, not instant success.

**Action IDs:**

| Scope | IDs | Role required |
|-------|-----|---------------|
| service | start, stop, restart | operator |
| vm | start, stop, shutdown, reboot | operator |
| container | start, stop, restart | operator |
| host | reboot, shutdown | maintainer |
| agent | self_update | maintainer |

---

## 8. Host roles & visible sections

Agents report `hostRole` and `capabilities.sections`:

| hostRole | Services | Containers | VMs |
|----------|----------|------------|-----|
| proxmox | — | if Docker on host | ✓ |
| ubuntu-server / vm-linux / generic-linux | ✓ | if Docker available | — |
| windows-server | ✓ | — | — |
| windows-client | partial | — | — |

Docker containers are reported by **agents on Linux VMs**, not by Proxmox hypervisors (unless Docker installed on hypervisor itself).

---

## 9. Current file map

```
apps/web/
├── index.html, main.js          Overview dashboard
├── devices.html, devices.js     Device hub
├── devices-servers.html         Server list
├── devices-clients.html         Client list
├── server.html, server.js       Host NOC detail (+ noc.css)
├── vms.html, vms.js             VM fleet
├── containers.html, containers.js   Docker fleet
├── security.html, security.js   Security integrations
├── admin.html, admin.js         Admin
├── login.html, login.js         Auth
├── common.js                    Shared utilities + nav
├── styles.css                   Global + dashboard styles
└── noc.css                      Server detail NOC styling
```

---

## 10. Component inventory (design targets)

| Component | Where used | Notes |
|-----------|------------|-------|
| App header + nav | All pages | Sticky top bar |
| Status pill | Overview sections | nominal / warning / error |
| Meter bar | Server fleet CPU/mem/storage | 3-up row |
| Compact data table | Overview servers, fleet pages | Sortable optional later |
| Door sensor row | Overview, Security | Highlight open |
| Camera preview tile | Overview, Security | 16:9 image, name label, refresh |
| Quick stat card | Overview bottom row | 2 stats + link |
| Server card | Devices pages | CPU/mem/storage/uptime |
| Action button row | VMs, containers, server | Hide invalid by state |
| Sub-nav tabs | Security, Devices | Panel switching |
| Empty / error state | All | Muted copy, no broken layout |
| Toast / inline status | Action queue feedback | Currently text under section head |

---

## 11. Responsive behavior

| Breakpoint | Behavior |
|------------|----------|
| Desktop | Security: doors left column, cameras right; server table full width |
| ≤1100px | Stack security panels; quick cards single column |
| Mobile | Horizontal scroll for tables; camera grid 2 columns min |

---

## 12. Design deliverables expected back

Provide to implementation agent:

1. **Figma-style spec or HTML mock** for each page (or one design system + page templates)
2. **Updated component list** with spacing, typography scale, border radius
3. **Overview wireframe** confirming section order: Security → Server Health → Quick links
4. **Interaction notes:** hover, focus, disabled actions, stale host styling
5. **Optional:** light theme tokens (not required v1)
6. **Do not redesign API contracts** unless paired with backend change request

Acceptable output formats:

- Static HTML/CSS prototype in a `design/` folder
- Detailed markdown + ASCII wireframes
- Exported CSS variables overriding `:root` in `styles.css`

---

## 13. Implementation handoff checklist

When passing design back to Cursor for implementation:

- [ ] Map mock classes to existing IDs in HTML (or list ID renames)
- [ ] Keep all `apiFetch` endpoints unchanged
- [ ] Preserve action gating logic (`*ActionAllowed` functions)
- [ ] Camera previews must use authenticated proxy URLs + `crossorigin="use-credentials"`
- [ ] Bump `?v=` cache on changed JS/CSS
- [ ] Test overview with live data: 3 Docker hosts, 4 cameras, 3 door sensors, 6+ servers

---

## 14. Example environment snapshot (reference)

Illustrative lab layout for designers — not a real site inventory:

| Asset | Count / notes |
|-------|----------------|
| Proxmox hypervisors | hypervisor01–03 |
| Docker host agents | appserver01, docker01 |
| Frigate cameras | driveway, porch, backyard |
| HA door sensors | front-door, garage, back-door |
| Windows DCs | HCC-DC1–3 (agents, no Docker) |

---

## 15. Product principles (from ARCHITECTURE.md)

- **“What is happening now?” before “where to click”**
- Summary-first, drilldown-second
- Controls close to health indicators
- Graceful degradation when agents stale or integrations offline

---

*Document version: 2026-07-04 — matches overview layout with Security section first.*
