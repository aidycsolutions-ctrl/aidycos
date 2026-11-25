#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${ROOT}/aidycos/nemo_actions"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
LEGACY_ICON="${DATA_HOME}/icons/hicolor/scalable/apps/aidyc-explorer.svg"
LEGACY_ICON_SHA256="3ef41ea2c06d988f26b327c046a22a64ac63bfa3e0daafd2fe4b1508a538a4c9"
FILES=(
  "${DATA_HOME}/nemo/actions/aidyc-change-usb-label.nemo_action|${SOURCE_DIR}/aidyc-change-usb-label.nemo_action"
  "${DATA_HOME}/nemo/actions/change_usb_label.py|${SOURCE_DIR}/change_usb_label.py"
  "${DATA_HOME}/applications/aidyc-explorer.desktop|${SOURCE_DIR}/aidyc-explorer.desktop"
  "${DATA_HOME}/icons/hicolor/512x512/apps/aidyc-explorer.png|${SOURCE_DIR}/aidyc-explorer.png"
)
removed=0

for item in "${FILES[@]}"; do
  IFS='|' read -r target source <<<"${item}"
  if [[ -f "${target}" ]]; then
    if cmp -s "${source}" "${target}"; then
      rm -- "${target}"
      removed=1
    else
      echo "Se conserva ${target} porque fue modificado." >&2
    fi
  fi
done

if [[ -f "${LEGACY_ICON}" ]]; then
  current_hash="$(sha256sum "${LEGACY_ICON}" | cut -d' ' -f1)"
  if [[ "${current_hash}" == "${LEGACY_ICON_SHA256}" ]]; then
    rm -- "${LEGACY_ICON}"
    removed=1
  else
    echo "Se conserva el icono anterior ${LEGACY_ICON} porque fue modificado." >&2
  fi
fi

rmdir "${DATA_HOME}/nemo/actions" 2>/dev/null || true
rmdir "${DATA_HOME}/nemo" 2>/dev/null || true
rmdir "${DATA_HOME}/icons/hicolor/512x512/apps" 2>/dev/null || true
rmdir "${DATA_HOME}/icons/hicolor/512x512" 2>/dev/null || true
rmdir "${DATA_HOME}/icons/hicolor/scalable/apps" 2>/dev/null || true
rmdir "${DATA_HOME}/icons/hicolor/scalable" 2>/dev/null || true
rmdir "${DATA_HOME}/icons/hicolor" 2>/dev/null || true
rmdir "${DATA_HOME}/icons" 2>/dev/null || true

if [[ "${removed}" == 1 ]]; then
  echo "Se retiraron la acción y el lanzador personalizados de AidyC Explorer."
  echo "Nemo y sus paquetes del sistema no se desinstalaron."
else
  echo "No había archivos de AidyC Explorer para retirar."
fi
