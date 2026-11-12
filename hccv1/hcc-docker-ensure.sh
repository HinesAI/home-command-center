#!/usr/bin/env bash
# Start watched Docker containers that are stopped after boot or an interrupted halt.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WATCH="${HCC_DOCKER_WATCH:-$ROOT/hcc-docker.watch}"

command -v docker >/dev/null 2>&1 || exit 0
systemctl is-active --quiet docker 2>/dev/null || exit 0
docker info >/dev/null 2>&1 || exit 0
[[ -r "$WATCH" ]] || exit 0

while IFS= read -r name || [[ -n "$name" ]]; do
	name="${name%%#*}"
	name="$(echo "$name" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
	[[ -z "$name" ]] && continue
	if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
		continue
	fi
	if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
		docker start "$name" >/dev/null 2>&1 || true
	fi
done < "$WATCH"
