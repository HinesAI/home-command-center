# HCC Terminal

HCC Terminal is the physical-console interface for Home Command Center. It
renders a full-screen ANSI dashboard on a Linux virtual terminal, normally
`tty1`, for an always-on local operational view.

This first version preserves the proven standalone collector while establishing
HCC Terminal as a Home Command Center application. The intended end state is for HCC Core to
own integration collection and normalization, with Terminal and Web consuming
the same state.

## Included

- Host, storage, network, service, container, GPU, and patch status
- Proxmox node and workload status
- UniFi VLAN, WAN, ping, and latest gateway speed-test status
- Home Assistant weather and door state
- Frigate camera/service status
- Ollama and RAGFlow status
- Optional daily email report
- Full-screen `tty1` systemd service and two-minute collection timer

## Layout

```text
apps/terminal/
  assets/       # Optional startup sound
  bin/          # Renderer, standalone collector, and helpers
  config/       # Safe defaults and secret-free examples
  systemd/      # Unit templates rendered by the installer
  install.sh
  uninstall.sh
```

Installed systems use separate paths:

```text
/opt/hcc-terminal       application files
/etc/hcc-terminal       configuration and credentials
/var/lib/hcc-terminal   generated snapshots and runtime state
```

## Requirements

Required:

- Linux with systemd and a local virtual terminal
- Bash
- Standard GNU/Linux userland (`awk`, `flock`, `free`, `getent`, `sed`)
- `curl` and `jq`
- `iproute2` (`ip` and `ss`)
- `iputils-ping`
- Python 3

Features are detected at runtime. Commands such as `docker`, `zpool`,
`nvidia-smi`, `aplay`, and Proxmox APIs are optional.

## Install

From the repository:

```bash
cd apps/terminal
sudo ./install.sh
```

This disables `getty@tty1`, installs HCC Terminal on `tty1`, and starts the
standalone collector timer. Use another virtual terminal, such as
`Ctrl+Alt+F2`, for a login shell.

To install files and units without taking over `tty1`:

```bash
sudo ./install.sh --no-start
```

## Configure

Runtime defaults are in:

```text
/etc/hcc-terminal/hcc-terminal.env
```

Optional integrations use separate files:

- `hcc-network.targets`
- `hcc-docker.watch`
- `hcc-proxmox.nodes`
- `hcc-proxmox.env`
- `hcc-unifi.env`
- `hcc-homeassistant.env`
- `hcc-ai.env`
- `hcc-email.env`

Copy the corresponding `.example` file before adding credentials:

```bash
sudo cp \
  /etc/hcc-terminal/hcc-unifi.env.example \
  /etc/hcc-terminal/hcc-unifi.env
sudo chmod 600 /etc/hcc-terminal/hcc-unifi.env
sudoedit /etc/hcc-terminal/hcc-unifi.env
sudo systemctl restart hcc-terminal-collect.service
```

Never commit populated `.env` files or API tokens.

## Operations

```bash
sudo systemctl status hcc-terminal
sudo systemctl restart hcc-terminal
sudo systemctl start hcc-terminal-collect.service
journalctl -u hcc-terminal -f
```

Remove the application while preserving configuration and state:

```bash
sudo ./uninstall.sh
```

Use `sudo ./uninstall.sh --purge` only when configuration and runtime history
should also be deleted.

## HCC Core transition

Standalone collection is a compatibility mode, not a second permanent HCC
backend. Migration should proceed integration-by-integration:

1. Register a bundled integration through the HCC plugin manifest.
2. Normalize its data in Core contracts.
3. Expose the data through Core API/widget queries.
4. Switch Terminal to the Core data source.
5. Retain local collection only for host boot/recovery status.

The future client settings are reserved in `hcc-terminal.env.example` as
`HCC_CORE_URL` and `HCC_CORE_TOKEN`.
