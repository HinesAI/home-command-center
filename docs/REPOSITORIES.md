# Repository layout and private overlays

This repository is the public Home Command Center platform.

Site-specific configuration (live secrets, LAN hostnames, custom branding, DNS notes)
belongs in a **private deployment overlay** — a separate private repo, fork, or host-local
files under `/etc/hcc` — not in this tree.

## What belongs here

- `apps/core`, `apps/agent`, `apps/agent-windows`, `apps/terminal`, `apps/web`
- `contracts`
- Shared `scripts/`
- Generic packaging under `deploy/` (`*.prod.example`, compose files, installer)
- Product docs with example hostnames (`example.local`, `192.168.1.x`)

## What should stay out of the public tree

- Populated `deploy/.env` or other live secrets
- Site DNS / firewall runbooks
- Internal branding-only templates
- Real inventory CSVs for your LAN (use the `*.example` / scrubbed samples only)

`scripts/sync-public-repo.sh` can copy shared platform paths into another checkout while
excluding internal-only filenames. Review the diff before you push.

## Branding

Shared code defaults to **Home Command Center**. Override at runtime if you want a
custom product name:

```bash
# deploy/.env or /etc/hcc/hcc.env
HCC_PRODUCT_NAME=My Lab Command Center
HCC_PRODUCT_SHORT_NAME=HCC
```

Terminal clients use the same variable in `/etc/hcc-terminal/hcc-terminal.env`.
Core exposes the resolved name on `GET /api/v1/system/version`.

## Optional: sync into a private overlay checkout

```bash
# From a private overlay checkout that vendors this platform:
./scripts/sync-public-repo.sh /path/to/home-command-center

# Or the reverse: push shared platform changes from a working tree into this repo
./scripts/sync-public-repo.sh /path/to/private-overlay
```

Always review `git status` in the target before committing.
