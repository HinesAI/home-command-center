# Agent Identity and Service Account Model

HCC agents should run under a dedicated identity, not an interactive admin and not `SYSTEM` in production.

## Goals

- Least privilege for heartbeat collection and allowlisted actions
- Auditable actions tied to a known service principal
- Safe path to agent self-update and future software deployment
- Same model across Windows (gMSA) and Linux (local service user)

## Recommended AD layout (WEB-FLIP example)

### Rollout order (one DC writes AD; replication syncs the domain)

All AD object creation happens on **one DC** (recommended: `HINESDC1`). AD replication distributes groups and the gMSA to every DC automatically. Do not create the same objects on multiple DCs.

**On HINESDC1 (elevated PowerShell):**

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
$base = "http://192.168.4.237:3000/downloads/ad"
$dir = "C:\Windows\Temp\hcc-ad"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest "$base/bootstrap-ad-from-dc.ps1" -OutFile "$dir\go.ps1" -UseBasicParsing
```

| Step | Command | What happens |
|------|---------|--------------|
| 1 | `& "$dir\go.ps1" -Phase Groups` | Creates all tier groups on HINESDC1 |
| 2 | `& "$dir\go.ps1" -Phase WaitGroups` | Polls HINESDC1/2/3 until groups exist everywhere |
| 3 | Host ACLs (each DC) | `setup-host-hcc-permissions.ps1 -HostRole dc` |
| 4 | `& "$dir\go.ps1" -Phase ServiceAccount` | Creates `svc-hcc-agent` gMSA on HINESDC1 |
| 5 | `& "$dir\go.ps1" -Phase WaitServiceAccount` | Polls until gMSA + group membership replicate |
| 6 | Agent install (each DC) | Bootstrap with `-RunAsAccount "WEB-FLIP\svc-hcc-agent$"` |

Groups created in step 1:

| Group | Purpose |
|-------|---------|
| `HCC-Agent-Observers` | Human dashboard read-only |
| `HCC-Agent-Operators` | Human service/VM controls via UI |
| `HCC-Agent-Maintainers` | Human agent update/restart via UI |
| `HCC-Agent-Deployers` | Human software install via UI |
| `HCC-Agent-ServiceAccounts` | Agent execution principals (gMSA added in step 4) |

Step 3 grants `WEB-FLIP\HCC-Agent-ServiceAccounts` local rights on each host (NTFS, batch logon, service start/stop). Run this after groups replicate but before or after gMSA creation.

Scripts live in `deploy/ad/` (`config.web-flip.psd1` lists DC names for replication checks).

### 1. Group Managed Service Account (preferred)

Use one gMSA for all HCC agents, or one per tier (servers vs DCs).

```powershell
# Prefer the bundled script (after tier groups + host ACLs):
.\setup-ad-service-account.ps1 -AllowedComputerNames HINESDC1,HINESDC2,HINESDC3

# Manual equivalent:
New-ADServiceAccount -Name "svc-hcc-agent" -DNSHostName "svc-hcc-agent.web-flip.local" -PrincipalsAllowedToRetrieveManagedPassword "HINESDC1$","HINESDC2$","HINESDC3$"
Add-ADGroupMember -Identity "HCC-Agent-ServiceAccounts" -Members (Get-ADServiceAccount svc-hcc-agent)
```

Install the gMSA on each host:

```powershell
Install-ADServiceAccount -Identity "svc-hcc-agent"
```

Scheduled task principal: `WEB-FLIP\svc-hcc-agent$`

### 2. Permission tiers (keep separate)

| Tier | AD group | Agent capability | Example actions |
|------|----------|------------------|-----------------|
| Observer | `HCC-Agent-Observers` | Collect metrics only | heartbeat |
| Operator | `HCC-Agent-Operators` | Allowlisted controls | service.start/stop, vm.start/stop |
| Maintainer | `HCC-Agent-Maintainers` | Agent lifecycle | agent.self_update, agent.restart |
| Deployer | `HCC-Agent-Deployers` | Software rollout | software.install (future) |

Do **not** make the agent account Domain Admin.

### 3. Windows local rights

On each managed server:

```powershell
# NTFS
icacls "C:\Program Files\HCC-Agent" /grant "WEB-FLIP\svc-hcc-agent$:(OI)(CI)RX"
icacls "C:\ProgramData\HCC-Agent" /grant "WEB-FLIP\svc-hcc-agent$:(OI)(CI)M"

# Log on as batch job (required for scheduled task)
ntrights +r SeBatchLogonRight -u "WEB-FLIP\svc-hcc-agent$"
```

Grant service control only for named services (example for DC):

```powershell
$sid = (Get-ADServiceAccount svc-hcc-agent).SID
# Use sc.exe SDDL or custom service ACL tooling for NTDS, DNS, DHCP, etc.
```

Host reboot/shutdown should remain a separate elevated action requiring Maintainer tier or manual approval.

### 4. Linux equivalent

Create a local service user on each host:

```bash
useradd --system --home-dir /opt/hcc-agent --shell /usr/sbin/nologin hcc-agent
chown -R hcc-agent:hcc-agent /opt/hcc-agent
```

Run `hcc-agent.service` as `User=hcc-agent`. Sudoers should allow only explicit commands in `/etc/sudoers.d/hcc-agent`.

## Agent configuration

Environment file keys:

| Variable | Purpose |
|----------|---------|
| `HCC_SERVICE_ACCOUNT` | Windows task RunAs account (`DOMAIN\user` or gMSA with `$`) |
| `HCC_AGENT_VERSION` | Reported to core; drives update eligibility |
| `HCC_AGENT_TOKEN` | Shared secret for core auth until mTLS |
| `HCC_AGENT_CAPABILITY_TIER` | Optional override: observer, operator, maintainer, deployer |

Installer flags:

```powershell
./install-windows-agent.ps1 `
  -CoreBaseUrl http://192.168.4.237:18080 `
  -NodeId hinesdc1 `
  -AgentId agent-hinesdc1 `
  -RunAsAccount "WEB-FLIP\svc-hcc-agent$"
```

## Dashboard authentication (AD + local break-glass)

Core auth is enabled by default in dev compose. Human users authenticate against WEB-FLIP AD; a local admin account provides emergency access if AD/LDAP fails.

### AD user setup

Add dashboard users to one or more human groups (not `HCC-Agent-ServiceAccounts`):

```powershell
Add-ADGroupMember -Identity "HCC-Agent-Operators" -Members "Jaleel"
Add-ADGroupMember -Identity "HCC-Agent-Maintainers" -Members "Jaleel"
```

Users must belong to at least one `HCC-Agent-*` group or login is rejected.

| Group | Dashboard role |
|-------|----------------|
| `HCC-Agent-Observers` | Read fleet |
| `HCC-Agent-Operators` | Queue service/VM actions |
| `HCC-Agent-Maintainers` | Admin agent updates |
| `HCC-Agent-Deployers` | Future software installs |

Login formats: `WEB-FLIP\username`, `username`, or `username@web-flip.local`.

### Local break-glass admin

Configured via core environment variables (see `apps/core/auth.env.example`):

- `HCC_LOCAL_ADMIN_USER` (default in dev compose: `hccadmin`)
- `HCC_LOCAL_ADMIN_PASSWORD` (change in production)

This account bypasses AD and has full dashboard permissions.

### Web login

Open `http://192.168.4.237:3000/login.html` (protected pages redirect there automatically).

## Core ↔ agent trust (phased)

1. **Now:** open heartbeats (dev), action allowlist from agent-reported capabilities
2. **Next:** `HCC_AGENT_TOKEN` validated by core; actions require authenticated UI user + audit log
3. **Later:** mTLS client cert per node or per gMSA
4. **Future:** signed action envelopes (request id, expiry, nonce) per ARCHITECTURE.md

## Remote agent update flow (planned)

1. Core stores target agent version + signed package URL + SHA256
2. Heartbeat response includes `pendingActions: [{ actionId: "agent.self_update", params: { version, url, sha256 } }]`
3. Maintainer-tier agent downloads to staging, verifies hash, runs local updater (stop task → replace files → start task)
4. Agent reports `actionResults` and new `HCC_AGENT_VERSION`

Bootstrap/install remain admin-driven until Maintainer tier is enabled.

## Future software installs (planned)

Treat software deployment as a separate plugin capability:

- Catalog in core (`softwarePackageId`, install script, checksum, supported roles)
- Action: `software.install` with params `{ packageId, version }`
- Only Deployer tier + core RBAC approval
- Agent runs signed bundle from local staging; never arbitrary shell from UI

Keep install scripts in core-managed artifact store, not inline in action payloads.

## Current state in this repo

- Windows agent scheduled task runs as **SYSTEM** unless `-RunAsAccount` is passed to installer
- Actions are allowlisted in agent code (`action_runner.py` / `heartbeat_sender.ps1`)
- Core queues actions from UI without auth/RBAC yet
- No self-update action implemented yet; version field is reserved
