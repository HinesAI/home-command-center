# HCC v1 — live appliance (tty1)

Current Hines Command Center **v1** stack as deployed on this host: tty1 dashboard, early console, Quadro/nouveau bind, boot/halt/reboot/update/maintenance screens, status collector, docker ensure, and nightly updates.

Snapshotted from `/Backup_Pool/scripts` (plus `/etc/systemd` drop-ins / `quadro600-console.service` and the installed `/usr/local/sbin/hcc-early-console.sh`).

## Layout

| Path | Role |
|------|------|
| `hines-command-center-dashboard.sh` | Main tty1 dashboard loop |
| `hcc-dashboard-fb.py` | Framebuffer dashboard paint |
| `hcc-appliance-boot.lib` / `hcc-appliance-screen.lib` | Boot/update screen helpers |
| `hcc-appliance-halt.sh` | Halt/reboot/shutdown narrative (`ExecStop`) |
| `hcc-boot-circle-fb.py` (+ preview gif/py) | Circular boot/status FB UI |
| `hcc-boot-preview*` / `hcc-halt-preview*` / reboot+shutdown gifs | Boot/halt preview assets |
| `hcc-early-console.sh` | Early tty1 hold until dashboard owns console (install to `/usr/local/sbin/`) |
| `hcc-nightly-updates.sh` | Maintenance/updates screen + apt run |
| `collect-hcc-status.sh` | Status JSON collector |
| `hcc-docker-ensure.sh` + `hcc-docker.watch` | Watched containers |
| `quadro600-bind-nouveau.sh` | GPU bind for console |
| `startup*.wav` / `loopsound.*` | Boot/loop audio |
| `systemd/` | Units, timers, sudoers snippet, printk/quiet conf, drop-ins |

## Secrets (not committed)

Copy examples → local env files (`chmod 600`):

- `hcc-proxmox.env.example` → `hcc-proxmox.env`
- `hcc-homeassistant.env.example` → `hcc-homeassistant.env`
- `hcc-unifi.env.example` → `hcc-unifi.env`
- `hcc-email.env.example` → `hcc-email.env`
- `hcc-ai.env.example` → `hcc-ai.env`
- Frigate credentials stay host-local (`hcc-frigate.env`)

Runtime state (`*.pid`, `*.lock`, `*.log`, `hcc-status.json`, etc.) is not included.

## Install hints

See `install-hcc-dashboard.sh` / `start-hcc-dashboard.sh`. Typical unit install path is `/etc/systemd/system/` from `systemd/`; early console belongs at `/usr/local/sbin/hcc-early-console.sh`.
