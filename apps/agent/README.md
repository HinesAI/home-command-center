# apps/agent

Small Linux heartbeat agent for Home Command Center.

## Files

- `heartbeat_sender.py`: collects host telemetry and posts heartbeats
- `hcc-agent.service`: systemd unit
- `install-linux-agent.sh`: one-command Linux installer
- `rollout-linux-agents.sh`: SSH rollout helper for many Linux hosts
- `agents.inventory.example.csv`: inventory template for rollout helper
- `hcc-agent.env.example`: env template (no hardcoded core host)

## Install On Linux Host (Proxmox/Ubuntu)

Copy `apps/agent` folder to the target host, then run:

```bash
sudo ./install-linux-agent.sh \
  --core-base-url "http://<hcc-core-host>:18080" \
  --node-id "proxmox-01" \
  --agent-id "agent-proxmox-01"
```

Default heartbeat interval is 120 seconds (override with `--interval`).

Or use explicit endpoint:

```bash
sudo ./install-linux-agent.sh \
  --core-heartbeat-url "http://<hcc-core-host>:18080/api/v1/agent/heartbeat" \
  --node-id "ubuntu-storage-01" \
  --agent-id "agent-ubuntu-storage-01"
```

## Verify

```bash
sudo systemctl status hcc-agent.service
sudo journalctl -u hcc-agent.service -f
```

## Reconfigure

Edit `/etc/hcc-agent.env`, then:

```bash
sudo systemctl restart hcc-agent.service
```

## Multi-Host Rollout

From your control machine:

```bash
cp agents.inventory.example.csv agents.inventory.csv
# edit agents.inventory.csv for your hosts
DRY_RUN=true ./rollout-linux-agents.sh ./agents.inventory.csv
./rollout-linux-agents.sh ./agents.inventory.csv
```

If you want to force a specific key:

```bash
SSH_IDENTITY_FILE=~/.ssh/id_ed25519_hcc_rollout ./rollout-linux-agents.sh ./agents.inventory.csv
```

