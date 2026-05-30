#!/usr/bin/env bash
# AnimaDex -- import the public catalogue from animadex.net (wizard).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "No .venv found -- run ./install.sh first."
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

cat <<'EOF'

============================================================
  AnimaDex  -  import the public catalogue from animadex.net
============================================================

  1) Sign in at https://animadex.net
  2) Open  Account  ->  "Offline dataset export"
  3) Click Generate token, then paste it below.

EOF

read -rp "Paste your export token: " TOKEN
if [ -z "${TOKEN:-}" ]; then
    echo "No token entered. Aborting."
    exit 1
fi

DATA_DIR=$(python -c "from animadex.config import load; print(load().paths.data_dir)")
echo
if [ -f "$DATA_DIR/.animadex_import_state.json" ]; then
    echo "An earlier import was found -- this run fetches only what changed (a fast delta update)."
else
    echo "No earlier import found -- this will be a full first import."
fi

echo
echo "Full-resolution images are MUCH larger (tens of GB) than thumbnails."
echo "Thumbnails alone are enough for a fully browsable gallery."
read -rp "Also download full-resolution images? (y/N): " ANS
IMG=""
case "$ANS" in [Yy]*) IMG="--with-images";; esac

echo
echo "Starting import..."
python scripts/import_from_site.py --token "$TOKEN" $IMG

echo
echo "Import finished. Start the gallery with:  ./run.sh"
