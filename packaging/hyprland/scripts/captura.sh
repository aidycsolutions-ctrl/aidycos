#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp --suffix=.png)"
trap 'rm -f "${tmp}"' EXIT

geometry="$(slurp)"
grim -g "${geometry}" "${tmp}"
wl-copy --type image/png <"${tmp}"

ask_to_save() {
  zenity --question \
  --title="Captura de pantalla" \
  --text="¿Quieres guardar esta captura?" \
  --ok-label="Guardar" \
  --cancel-label="No guardar" &
  dialog_pid=$!
  focused_once=0
  while kill -0 "${dialog_pid}" 2>/dev/null; do
    active_pid="$(hyprctl -j activewindow 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("pid", ""))' 2>/dev/null || true)"
    if [[ "${active_pid}" == "${dialog_pid}" ]]; then
      focused_once=1
    elif [[ "${focused_once}" == 1 ]]; then
      # Treat clicking another window (or switching away) as “No guardar”.
      kill "${dialog_pid}" 2>/dev/null || true
      wait "${dialog_pid}" 2>/dev/null || true
      return 1
    fi
    sleep 0.1
  done
  wait "${dialog_pid}"
}

if ask_to_save; then
  capture_dir="${HOME}/Imágenes/Capturas"
  mkdir -p "${capture_dir}"
  stamp="$(date +%Y-%m-%d_%H-%M-%S)"
  cp "${tmp}" "${capture_dir}/captura-${stamp}.png"
  zenity --notification --text="Captura guardada en Imágenes/Capturas"
fi
