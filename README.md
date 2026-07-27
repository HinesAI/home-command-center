# Home Command Center (HCC)

**Current platform release: v2.1.0**

Home Command Center is the unified product name for the dashboard, Core API, kiosk, gate, and connected agents. HCC is a cross-platform infrastructure and home operations dashboard: fleet health, security, weather, climate, and network status in one touch-friendly interface.

It does **not** replace Proxmox, Docker, Active Directory, Frigate, or Home Assistant — it sits above them and provides a unified operational view.

## Repositories

This project is maintained in two GitHub repositories:

| Repository | Visibility | Purpose |
|------------|------------|---------|
| [home-command-center](https://github.com/HinesAI/home-command-center) | Public | Shareable upstream, default **Home Command Center** branding |
| [HCCv2](https://github.com/HinesAI/HCCv2) | Private | Internal production deployment and site-specific config |

Shared platform code (Core, agents, dashboard, terminal, packaging) is synced between both repos with `scripts/sync-public-repo.sh`. See `docs/REPOSITORIES.md` for the workflow.

Custom branding (for example **Hines Command Center**) is set with `HCC_PRODUCT_NAME` and does not require a fork.

## Versioning and product names

HCC uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **Major**: incompatible platform, API, or deployment changes
- **Minor**: backward-compatible features and substantial dashboard updates
- **Patch**: backward-compatible fixes

The repository-root `VERSION` file is the release source of truth. Update it once per release and include the version in the release commit/tag (for example, `v2.1.0`).

Current unified component names:

- **Home Command Center** / **HCC** — the complete product
- **HCC Dashboard** — the primary web interface
- **HCC Core** — common API, auth, state, and integrations backend
- **HCC Gate** — public read-only landing and sign-in experience
- **HCC Kiosk** — wall and tablet displays
- **HCC Agent** — Linux and Windows host collectors

These are names within one product and repository; they do not imply separate programs or deployments.

## What's included

### Dashboard (`apps/web`)

| Page | Purpose |
|------|---------|
| `index.html` | Overview — weather, security glance, server health, quick links |
| `kiosk.html` | Wall / iPad kiosk — weather, security, automations (landscape, touch) |
| `security.html` | Frigate cameras + Home Assistant door sensors |
| `climate.html` | Sensi thermostat controls via Home Assistant |
| `devices*.html` | Enrolled servers and clients |
| `vms.html` / `containers.html` | VM and Docker fleet views |
| `server.html` | Per-host NOC detail (services, metrics, history) |
| `services.html` | Fleet-wide service inventory |
| `admin.html` | Agent releases and rollout |

### Core API (`apps/core`)

- Fleet overview, per-node detail, history
- Agent heartbeats (Linux + Windows)
- LDAP + local break-glass auth
- Integrations: **Open-Meteo weather**, **Home Assistant** (doors + Sensi climate), **Frigate** (cameras)
- Allowlisted service/VM/container actions

### HCC Terminal (`apps/terminal`)

- Full-screen Linux physical-console dashboard, normally on `tty1`
- Standalone compatibility collector for host and infrastructure status
- Installable systemd renderer, collection timer, and optional daily report
- Planned Core-connected mode so Web and Terminal share normalized state

### Agents

- **Linux** (`apps/agent`) — systemd service enumeration, heartbeat v1.0.3
- **Windows** (`apps/agent-windows`) — all services via WinSW, heartbeat v1.0.7
- One-line installers published under `apps/web/downloads/`

## Quick start

1. Copy secrets and site config:
   ```bash
   cp deploy/.env.example deploy/.env
   # Edit deploy/.env (HA token, LDAP, break-glass password, weather coords)
   ```
2. Start the stack:
   ```bash
   cd deploy
   docker compose -f docker-compose.dev.yml up -d
   ```
3. Open the dashboard at the hostname configured in Caddy (see `deploy/Caddyfile`).

## Build a portable Ubuntu package

Build the production Core and Web images and create a self-contained LAN deployment archive:

```bash
sudo bash scripts/build-hcc-package.sh
```

Output:

```text
dist/hcc-v2.1.0-linux-amd64.tar.gz
dist/hcc-v2.1.0-linux-amd64.tar.gz.sha256
```

Copy both files to the destination Ubuntu server, verify the checksum, extract the archive, and run:

```bash
sudo ./install-hcc.sh \
  --hostname hcc.local \
  --bind 0.0.0.0 \
  --port 80
```

The production stack exposes only Caddy. Core and Web remain private on the Docker network. Persistent configuration is stored under `/etc/hcc`, releases under `/opt/hcc`, and fleet state in the `hcc_hcc-core-data` Docker volume.

See `deploy/PACKAGE-README.md` for firewall, upgrade, backup, and restore instructions.

## Configuration

| Variable | Purpose |
|----------|---------|
| `HCC_PRODUCT_NAME` | Dashboard and API product label (default: `Home Command Center`) |
| `HCC_PRODUCT_SHORT_NAME` | Short label (default: `HCC`) |
| `HCC_HA_URL` / `HCC_HA_TOKEN` | Home Assistant (doors, Sensi thermostat) |
| `HCC_FRIGATE_URL` | Frigate NVR camera previews |
| `HCC_WEATHER_*` | Open-Meteo location and label |
| `HCC_LDAP_*` | Active Directory auth |
| `HCC_LOCAL_ADMIN_*` | Break-glass local admin |

See `deploy/.env.example` and `apps/core/auth.env.example`.

## Repo layout

```text
apps/
  core/           # HCC Core API
  agent/          # Linux agent
  agent-windows/  # Windows agent + installers
  terminal/       # Linux tty physical-console client
  web/            # Static dashboard + downloads
contracts/        # OpenAPI + JSON schemas
deploy/           # docker-compose + rollout scripts
docs/             # Architecture and frontend briefs
scripts/          # Packaging and repo sync helpers
```

## Roadmap (in progress)

- [x] Home Assistant climate (Sensi thermostat) — overview, kiosk, and Climate Controls page
- [ ] Camera carousel when fleet grows
- [ ] Scenes / lighting automations on kiosk

## Linux agent onboarding

```bash
cd apps/agent
sudo ./install-linux-agent.sh \
  --core-base-url "http://<hcc-core-host>:18080" \
  --node-id "<unique-node-id>" \
  --agent-id "<unique-agent-id>"
```

Bulk rollout: `apps/agent/rollout-linux-agents.sh` + inventory CSV.

## Windows agent

Elevated PowerShell on each host:

```powershell
Invoke-WebRequest "http://<hcc-web>:3000/downloads/setup-hcc-agent.ps1" -OutFile $env:TEMP\setup-hcc-agent.ps1 -UseBasicParsing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\setup-hcc-agent.ps1
```
