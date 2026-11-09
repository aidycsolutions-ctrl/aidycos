#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp --suffix=.png)"
trap 'rm -f "${tmp}"' EXIT

geometry="$(slurp)"
grim -g "${geometry}" "${tmp}"
wl-copy --type image/png <"${tmp}"

if zenity --question \
  --title="Captura de pantalla" \
  --text="¿Quieres guardar esta captura?" \
  --ok-label="Guardar" \
  --cancel-label="No guardar"; then
  capture_dir="${HOME}/Imágenes/Capturas"
  mkdir -p "${capture_dir}"
  stamp="$(date +%Y-%m-%d_%H-%M-%S)"
  cp "${tmp}" "${capture_dir}/captura-${stamp}.png"
  zenity --notification --text="Captura guardada en Imágenes/Capturas"
fi
