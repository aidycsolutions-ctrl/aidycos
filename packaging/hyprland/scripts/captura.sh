#!/usr/bin/env bash
# Region screenshot → clipboard, then ask whether to save the file.
# Losing focus on the save dialog counts as “No guardar”.
set -euo pipefail

tmp="$(mktemp --suffix=.png)"
trap 'rm -f "${tmp}"' EXIT

geometry="$(slurp)"
grim -g "${geometry}" "${tmp}"
wl-copy --type image/png <"${tmp}"

_active_window_json() {
  hyprctl -j activewindow 2>/dev/null || true
}

_is_save_dialog() {
  local json="$1"
  [[ -n "${json}" ]] || return 1
  printf '%s' "${json}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
title = str(data.get("title") or "")
klass = str(data.get("class") or data.get("initialClass") or "")
ok = (
    "Captura de pantalla" in title
    or "zenity" in klass.casefold()
    or "Zenity" in klass
)
raise SystemExit(0 if ok else 1)
'
}

ask_to_save() {
  zenity --question \
    --title="Captura de pantalla" \
    --text="¿Quieres guardar esta captura?" \
    --ok-label="Guardar" \
    --cancel-label="No guardar" &
  dialog_pid=$!
  focused_once=0
  while kill -0 "${dialog_pid}" 2>/dev/null; do
    active="$(_active_window_json)"
    if _is_save_dialog "${active}"; then
      focused_once=1
    elif [[ "${focused_once}" == 1 ]]; then
      # Clicked elsewhere / switched away → same as “No guardar”.
      kill "${dialog_pid}" 2>/dev/null || true
      wait "${dialog_pid}" 2>/dev/null || true
      return 1
    fi
    sleep 0.1
  done
  if wait "${dialog_pid}"; then
    return 0
  fi
  return 1
}

if ask_to_save; then
  capture_dir="${HOME}/Imágenes/Capturas"
  mkdir -p "${capture_dir}"
  stamp="$(date +%Y-%m-%d_%H-%M-%S)"
  cp "${tmp}" "${capture_dir}/captura-${stamp}.png"
  zenity --notification --text="Captura guardada en Imágenes/Capturas" || true
fi
