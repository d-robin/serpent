#!/usr/bin/env bash
# Rebuild all SVGs, convert text to outlines, export PNGs. Needs Inkscape.
set -euo pipefail
cd "$(dirname "$0")"
IK="${INKSCAPE:-$(command -v inkscape || echo /Applications/Inkscape.app/Contents/MacOS/inkscape)}"
python3 _build.py
# outline text so wordmarks render identically without the font installed
for f in *wordmark*.svg social-card.svg banner.svg; do
  "$IK" "$f" --export-text-to-path --export-plain-svg -o "_tmp.svg" >/dev/null 2>&1 && mv _tmp.svg "$f"
done
mkdir -p png
png() { "$IK" "$1" -o "png/$2" -w "$3" ${4:+-h "$4"} >/dev/null 2>&1; }
for n in serpent snake-charmer; do
  for w in 32 180 512; do png "$n-favicon.svg" "$n-favicon-$w.png" $w; done
  png "$n-logo-dark.svg" "$n-logo-dark-512.png" 512
  png "$n-logo-light.svg" "$n-logo-light-512.png" 512
  png "$n-wordmark-dark.svg" "$n-wordmark-dark-1520.png" 1520
  png "$n-wordmark-light.svg" "$n-wordmark-light-1520.png" 1520
done
png social-card.svg social-card.png 1280 640
png banner.svg banner.png 2000 520
echo done
