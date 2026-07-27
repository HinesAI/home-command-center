# Home Command Center LAN package

This package installs the HCC Core API, Web dashboard, and Caddy gateway on an Ubuntu server. Container images are included, so HCC itself does not need to be downloaded from a registry.

Docker installation requires Ubuntu package-repository access when Docker Engine and Compose are not already installed.

## Install

1. Verify the archive checksum before extracting:

   ```bash
   sha256sum -c hcc-v2.1.0-linux-amd64.tar.gz.sha256
   ```

2. Extract and run the installer:

   ```bash
   tar -xzf hcc-v2.1.0-linux-amd64.tar.gz
   cd hcc-v2.1.0-linux-amd64
   sudo ./install-hcc.sh \
     --hostname hcc.web-flip.local \
     --bind 0.0.0.0 \
     --port 80
   ```

3. Create an internal DNS record for the selected hostname and point it to the server's LAN address.

4. Edit `/etc/hcc/hcc.env` to add Home Assistant and UniFi tokens or adjust site-specific integration addresses:

   ```bash
   sudoedit /etc/hcc/hcc.env
   sudo docker compose \
     --env-file /etc/hcc/compose.env \
     -f /opt/hcc/current/compose.yml \
     up -d
   ```

The installer generates a random authentication secret and initial local administrator password on first installation. Existing configuration is preserved during upgrades.

## LAN and VPN access

Only Caddy is published on the host. Core and Web remain private on the Docker network.

Restrict the configured HTTP port to trusted LAN and VPN networks. Example UFW rules:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 80 proto tcp
sudo ufw allow from 10.0.0.0/8 to any port 80 proto tcp
```

Use the actual LAN and VPN CIDRs for the deployment. Do not add an unrestricted public rule.

## Operations

```bash
# Status
sudo docker compose --env-file /etc/hcc/compose.env -f /opt/hcc/current/compose.yml ps

# Logs
sudo docker compose --env-file /etc/hcc/compose.env -f /opt/hcc/current/compose.yml logs -f

# Restart
sudo docker compose --env-file /etc/hcc/compose.env -f /opt/hcc/current/compose.yml restart

# Stop
sudo docker compose --env-file /etc/hcc/compose.env -f /opt/hcc/current/compose.yml down
```

Do not add `--volumes` when stopping unless HCC Core's persisted fleet and action state should be deleted.

## Upgrade

Copy and extract a newer package, then run its installer with the same hostname, bind address, and port. The installer changes `/opt/hcc/current` to the new release and preserves:

- `/etc/hcc/hcc.env`
- `/etc/hcc/compose.env`
- the `hcc_hcc-core-data` Docker volume

## Backup and restore

Back up configuration:

```bash
sudo tar -czf hcc-config-backup.tar.gz /etc/hcc
```

Back up Core state:

```bash
sudo docker run --rm \
  -v hcc_hcc-core-data:/data:ro \
  -v "$PWD":/backup \
  alpine:3.20 \
  tar -czf /backup/hcc-core-data.tar.gz -C /data .
```

Restore the archive into the same named volume before starting HCC.

## Optional clients

The `clients` directory contains source bundles for HCC Terminal and the Linux agent. These remain separately installed clients and are not started on the central HCC server automatically.
