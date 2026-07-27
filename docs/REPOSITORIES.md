# Dual-repository workflow

Home Command Center platform code is shared between two GitHub repositories:

| Remote | Repository | Role |
|--------|------------|------|
| `origin` | `HinesAI/HCCv2` | Private internal deployment (site config, production secrets, Hines branding) |
| `public` | `HinesAI/home-command-center` | Public upstream (default Home Command Center branding) |

Develop features in either checkout. When Core, agent, dashboard, terminal, or packaging changes are ready, sync them to the other repository before tagging a release.

## What is shared

These paths are kept in sync between repos:

- `apps/core`
- `apps/agent`
- `apps/agent-windows`
- `apps/terminal`
- `apps/web`
- `contracts`
- `scripts` (except local-only helpers you add under `scripts/local/`)
- `deploy/Caddyfile.prod`, `deploy/docker-compose.*.yml`, `deploy/install-hcc.sh`, `deploy/PACKAGE-README.md`, `deploy/hcc.env.prod.example`
- `VERSION`, `CHANGELOG.md`, `README.md`, `.dockerignore`
- Generic docs under `docs/` (see exclusions below)

## What stays internal (`HCCv2` only)

- `deploy/.env` and other live secrets
- `deploy/Caddyfile` (dev hostname routing for your LAN)
- `deploy/DNS-hcc.web-flip.local.md`
- `docs/INTERNAL-HINES.md`
- `deploy/hcc.env.internal.example` (Hines branding template)

The public repo should not contain site-specific hostnames, credentials, or internal runbooks.

## Branding without forking

Shared code defaults to **Home Command Center**. Internal deployments override branding at runtime:

```bash
# deploy/.env or /etc/hcc/hcc.env
HCC_PRODUCT_NAME=Hines Command Center
HCC_PRODUCT_SHORT_NAME=HCC
```

Terminal clients use the same variable in `/etc/hcc-terminal/hcc-terminal.env`.

Core exposes the resolved name on `GET /api/v1/system/version`. Web and kiosk UIs read that endpoint on load.

## Sync script

From your `HCCv2` checkout (after committing platform changes):

```bash
# One-time: clone the public repo beside HCCv2
git clone git@github-hinesai:HinesAI/home-command-center.git ../home-command-center

# Sync shared paths into the public checkout
./scripts/sync-public-repo.sh ../home-command-center

# Review and push from the public checkout
cd ../home-command-center
git status
git add -A
git commit -m "Sync platform changes from HCCv2"
git push origin main
```

To pull public changes back into the internal repo, run the same script from `home-command-center` pointing at your `HCCv2` path (or use `git remote` + cherry-pick for selective merges).

## Recommended release flow

1. Implement the feature on `main` in `HCCv2`.
2. Bump `VERSION` and update `CHANGELOG.md`.
3. Run `./scripts/sync-public-repo.sh ../home-command-center`.
4. Commit and push **both** repositories.
5. Tag the same version in both repos (`v2.1.0`).
6. Build packages from either checkout (`scripts/build-hcc-package.sh`).

## Git remotes (optional)

Add the public repo as a second remote in your internal checkout:

```bash
git remote add public git@github-hinesai:HinesAI/home-command-center.git
git fetch public
```

Use the sync script for directory-level updates; use remotes when you need to inspect history or cherry-pick individual commits.
