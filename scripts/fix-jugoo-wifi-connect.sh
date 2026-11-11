#!/usr/bin/env bash
# Fix Jugoo Wi-Fi UI: the control-center popup used a 2-arg lambda and dropped
# the SSID, so Connect crashed silently while `nmcli device wifi connect` worked.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-/opt/aidyc/jugoo}"

if [[ ! -d "${TARGET}/shell" ]]; then
  echo "No hay Jugoo en ${TARGET}" >&2
  exit 1
fi

python3 "${ROOT}/packaging/jugoo-overlay/install.py" "${TARGET}"
echo "Overlay de red aplicado en ${TARGET}"
echo "Reinicia Jugoo:"
echo "  pkill -f 'python3 -m shell'; /usr/local/bin/jugoo &"
