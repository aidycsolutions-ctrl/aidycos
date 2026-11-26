#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PRESERVE_MODIFIED=0
for arg in "$@"; do
  case "$arg" in
    --preserve-modified) PRESERVE_MODIFIED=1 ;;
    -h|--help) echo "Uso: install-aidyc-explorer.sh [--preserve-modified]"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done
SOURCE_DIR="${ROOT}/aidycos/nemo_actions"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
ACTION_DIR="${DATA_HOME}/nemo/actions"
APP_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons/hicolor/512x512/apps"
LEGACY_ICON="${DATA_HOME}/icons/hicolor/scalable/apps/aidyc-explorer.svg"
LEGACY_ICON_SHA256="3ef41ea2c06d988f26b327c046a22a64ac63bfa3e0daafd2fe4b1508a538a4c9"
# Lanzador de Nemo que duplicaba AidyCExplorer en el menú. Ya no se instala;
# si quedó de una versión anterior, se retira.
DUPLICATE_LAUNCHER="${APP_DIR}/aidyc-explorer.desktop"
FILES=(
  "${ACTION_DIR}/aidyc-change-usb-label.nemo_action|${SOURCE_DIR}/aidyc-change-usb-label.nemo_action|0644"
  "${ACTION_DIR}/change_usb_label.py|${SOURCE_DIR}/change_usb_label.py|0755"
  "${ICON_DIR}/aidyc-explorer.png|${SOURCE_DIR}/aidyc-explorer.png|0644"
)

needs_replace=0
for item in "${FILES[@]}"; do
  IFS='|' read -r target source _mode <<<"${item}"
  if [[ -e "${target}" ]] && ! cmp -s "${source}" "${target}"; then
    needs_replace=1
  fi
done

if [[ -f "${LEGACY_ICON}" ]]; then
  current_hash="$(sha256sum "${LEGACY_ICON}" | cut -d' ' -f1)"
  if [[ "${current_hash}" == "${LEGACY_ICON_SHA256}" ]]; then
    rm -- "${LEGACY_ICON}"
  else
    echo "Se conserva el icono anterior ${LEGACY_ICON} porque fue modificado." >&2
  fi
fi

if [[ -f "${DUPLICATE_LAUNCHER}" ]] \
  && grep -qx 'Name=AidyC Explorer' "${DUPLICATE_LAUNCHER}" \
  && grep -qx 'Exec=nemo %U' "${DUPLICATE_LAUNCHER}"; then
  rm -- "${DUPLICATE_LAUNCHER}"
  echo "Se retiró el lanzador duplicado AidyC Explorer; el menú usa AidyCExplorer." >&2
fi

if [[ "${needs_replace}" == 1 && "${PRESERVE_MODIFIED}" == 1 ]]; then
  echo "Los archivos distintos del instalador se conservarán; se añadirán los que faltan."
elif [[ "${needs_replace}" == 1 ]]; then
  if [[ ! -t 0 ]]; then
    echo "Hay archivos de AidyC Explorer distintos. Ejecuta este instalador en una terminal interactiva para confirmar la actualización." >&2
    exit 1
  fi
  read -r -p "Los archivos existentes difieren de esta versión. ¿Actualizar la integración? [s/N] " answer
  if [[ "${answer,,}" != "s" && "${answer,,}" != "si" ]]; then
    echo "No se modificaron los archivos." >&2
    exit 1
  fi
fi

for item in "${FILES[@]}"; do
  IFS='|' read -r target source mode <<<"${item}"
  if [[ "${PRESERVE_MODIFIED}" == 1 && -e "${target}" ]] && ! cmp -s "${source}" "${target}"; then
    echo "Se conserva ${target} porque fue modificado." >&2
    continue
  fi
  mkdir -p "$(dirname "${target}")"
  install -m "${mode}" "${source}" "${target}"
done

echo "La acción de etiqueta USB quedó integrada en Nemo para este usuario."
echo "El explorador del menú es AidyCExplorer (Super+E); no se instala un segundo lanzador."
echo "Cierra y vuelve a abrir Nemo para cargar la acción de etiqueta USB."
