# HCC Architecture (V1)

## 1. Runtime Components

## HCC Core

Single logical control-plane service (can later split horizontally):

- API Gateway (REST + WebSocket)
- Fleet State Aggregator
- Alert Engine
- Layout/Widget Service
- Auth/RBAC + Audit Logger
- Plugin Host (manifest-driven registration)

## HCC Agent

Runs on every node (Linux/Windows/Server Core first):

- Collectors: cpu/mem/disk/network/service/log tails
- Action Runner: allowlisted commands only
- Local cache of fleet snapshot and node state
- Bi-directional transport to core (HTTPS/WebSocket)

## HCC Clients

HCC Web and HCC Terminal are peer presentation clients:

- Web provides browser, tablet, and kiosk interaction.
- Terminal provides an always-on Linux physical-console view.
- Both consume normalized Core resources and widget/data-query contracts.
- Terminal retains a standalone collector only as a migration and recovery mode;
  infrastructure integrations must not permanently diverge between clients.

## 2. Data Model (Canonical)

Everything normalizes to these top-level resources:

- `Node`
- `Service`
- `Metric`
- `Alert`
- `ActionRequest` / `ActionResult`
- `DashboardLayout`
- `WidgetDefinition`

Agents publish canonical payloads; core never relies on OS-specific response formats.

## 3. Security Model (Required)

- Agent/Core mutual trust token or mTLS (mTLS preferred in V1.1)
- Role-based action authorization on core
- Signed action envelope (request id + nonce + expiry)
- Full audit records for every state-changing operation

## 4. Sync and Failure Behavior

- Agent heartbeats every N seconds (configurable)
- Agent queue persists transient outage events locally
- Core marks node stale when heartbeat TTL exceeded
- Dashboard degrades gracefully with last-known snapshots

## 5. Plugin Model (V1-safe)

V1 uses manifest + server-side registration:

- plugin declares:
  - service types
  - metric providers
  - action providers
  - widget definitions
- core validates plugin manifest schema
- UI reads widget registry from core, not hardcoded feature flags

Bundled integrations move into Core plugins incrementally. A plugin owns
vendor-specific collection and normalization; clients own rendering only.
Third-party plugin isolation and process boundaries are deferred until the
bundled manifest lifecycle is stable.

## 6. UX Rules

- “What is happening now?” appears before “where to click”
- Main dashboards are summary-first, drilldown-second
- Keep control actions close to health indicators
- Mobile/tablet layouts first; desktop can add density

