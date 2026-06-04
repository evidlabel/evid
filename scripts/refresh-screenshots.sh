#!/usr/bin/env bash
# Regenerate docs/assets SVGs using shellplot.
# Run from the repo root: bash scripts/refresh-screenshots.sh
#
# Requires shellplot: uv tool install shellplot
# demo.svg also requires a populated evid dataset (real data, local only).

set -euo pipefail
cd "$(dirname "$0")/.."

OUT=docs/assets
FONT=13
WIDTH=120

echo "→ help.svg"
shellplot svg single "uv run evid -h 2>/dev/null" \
  -o "$OUT/help.svg" --width $WIDTH --font-size $FONT

echo "→ demo.svg  (needs real data)"
shellplot svg multi "$OUT/demo.sh" \
  -o "$OUT/demo.svg" --width $WIDTH --font-size $FONT --output-delay 3

echo "Done. Updated: $OUT/help.svg  $OUT/demo.svg"
