#!/usr/bin/env bash
# Ensure Quadro 600 is driven by nouveau for text console (tty1).
set -euo pipefail
DEV="0000:65:00.0"
SYS="/sys/bus/pci/devices/$DEV"

if [[ ! -d "$SYS" ]]; then
  echo "Quadro 600 not present at $DEV" >&2
  exit 0
fi

modprobe nouveau modeset=1 2>/dev/null || modprobe nouveau || true

echo nouveau >"$SYS/driver_override" || true

cur=""
if [[ -L "$SYS/driver" ]]; then
  cur="$(basename "$(readlink -f "$SYS/driver")")"
fi

if [[ "$cur" == "nouveau" ]]; then
  echo "Quadro 600 already on nouveau"
  exit 0
fi

if [[ -n "$cur" && -e "/sys/bus/pci/drivers/$cur/unbind" ]]; then
  echo "$DEV" >"/sys/bus/pci/drivers/$cur/unbind" || true
  sleep 0.5
fi

# Re-enable if nvidia left it disabled
if [[ -w "$SYS/enable" ]]; then
  echo 1 >"$SYS/enable" 2>/dev/null || true
fi

if [[ -e /sys/bus/pci/drivers/nouveau/bind ]]; then
  echo "$DEV" >/sys/bus/pci/drivers/nouveau/bind 2>/dev/null || true
fi

sleep 0.5
if [[ -L "$SYS/driver" ]]; then
  echo "Quadro 600 driver: $(basename "$(readlink -f "$SYS/driver")")"
else
  echo "WARNING: Quadro 600 still unbound" >&2
  exit 1
fi
