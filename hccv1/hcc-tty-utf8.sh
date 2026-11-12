#!/usr/bin/env bash
# Restore UTF-8 console font after DRM/nouveau bind (HCC tty1).
set -euo pipefail
TTY=/dev/tty1
FONT=""
for f in \
  /usr/share/consolefonts/Uni2-TerminusBold16.psf.gz \
  /usr/share/consolefonts/Uni2-Terminus16.psf.gz \
  /usr/share/consolefonts/Uni2-Fixed16.psf.gz; do
  [[ -f "$f" ]] && FONT="$f" && break
done
if [[ -n "$FONT" ]] && [[ -w "$TTY" ]]; then
  setfont -C "$TTY" "$FONT" || true
  printf "\033%%G" >"$TTY" || true
fi
