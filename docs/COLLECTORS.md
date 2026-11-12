# Collector runtime (staging)

The collector system runs **alongside** the existing `/api/v1/integrations/*` endpoints.
**By default, the dashboard still uses legacy integrations** — collectors only populate
staging snapshots until you change routing.

## Integration source modes

| Mode | API behavior | Legacy API pull |
|------|----------------|-----------------|
| `legacy` (default) | `integrations.py` only | enabled |
| `collector` | collector snapshot, fallback to legacy | enabled |
| `collector-only` | collector snapshot only | disabled for that service |

Per-service env vars:

```bash
HCC_SOURCE_WEATHER=legacy          # weather API source
HCC_LEGACY_WEATHER=true            # allow legacy pull (default true except in collector-only)
```

Global default:

```bash
HCC_INTEGRATION_SOURCE=legacy
```

## Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/collectors` | Collector registry, health, and summary counts |
| `GET /api/v1/collectors/migration` | Per-service routing mode and migration status |
| `GET /api/v1/collectors/{id}` | Last normalized snapshot for one collector |

## Default collectors

| ID | Type | Legacy integration |
|----|------|--------------------|
| `fleet-agents` | `agent` | fleet heartbeats (staging only) |
| `homeassistant` | `homeassistant` | HA entity scan (staging only) |
| `weather` | `service` | `/api/v1/integrations/weather` |
| `network` | `service` | `/api/v1/integrations/network` |
| `security` | `service` | `/api/v1/integrations/security` |
| `climate` | `service` | `/api/v1/integrations/climate` |

## Migration workflow

1. **Stage (now)** — collectors run in background; APIs stay on `legacy`
2. **Canary** — set `HCC_SOURCE_weather=collector` and compare responses
3. **Greenlight** — run `scripts/greenlight-collector-migration.sh` to switch APIs to `collector-only` and disable legacy pulls for weather, network, security, and climate
4. **Rollback** — `scripts/rollback-collector-migration.sh` restores legacy routing

```bash
# Check routing status
curl -s http://127.0.0.1:18080/api/v1/collectors/migration | jq .

# After validation, cut over
./scripts/greenlight-collector-migration.sh --restart-core
```

See `deploy/collector-migration.env.example` for all flags.

## Configuration

- `HCC_COLLECTORS_ENABLED=true` — background collector runtime (default: on)
- `HCC_COLLECTORS_TICK_SECONDS=5` — scheduler tick
- `HCC_COLLECTORS_CONFIG` — optional registry JSON override
- `HCC_INTEGRATION_SOURCE_DEBUG=true` — add `_integrationSource` to API payloads

Example registry: `deploy/collectors.example.json`

Collectors never block existing request handlers. If a collector fails before
greenlight, legacy endpoints are unaffected.

## Admin GUI and CLI

The same settings schema is exposed in three places:

| Surface | Usage |
|---------|--------|
| **Admin → Platform settings** | Maintainer GUI for collectors, routing, integrations |
| **`scripts/hcc-settings`** | CLI against Core API (`list`, `get`, `set`, `greenlight-collectors`) |
| **`/app/data/hcc-settings.env`** | Persisted overlay written by GUI/CLI (hot-reloadable keys apply immediately) |

```bash
./scripts/hcc-settings list
./scripts/hcc-settings set HCC_SOURCE_WEATHER=collector
./scripts/hcc-settings migration
./scripts/hcc-settings greenlight-collectors
```
