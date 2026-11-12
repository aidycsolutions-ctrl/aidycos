#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_MODE=0
if [[ "${1:-}" == "--user" ]]; then
  USER_MODE=1
fi

can_sudo() {
  sudo -n true >/dev/null 2>&1
}

if [[ "${USER_MODE}" != 1 ]] && ! can_sudo; then
  echo "Sin sudo no interactivo; instalando en el usuario (~/.local). Usa --user o vuelve a lanzar con sudo."
  USER_MODE=1
fi

install_icons() {
  local dest_root="$1"
  local icon_size
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "$ROOT/packaging/aidyship/icons/aidyship-${icon_size}.png" ]]; then
      install -D -m 0644 \
        "$ROOT/packaging/aidyship/icons/aidyship-${icon_size}.png" \
        "${dest_root}/icons/hicolor/${icon_size}x${icon_size}/apps/aidyship.png"
    fi
  done
}

if [[ "${USER_MODE}" == 1 ]]; then
  SHARE="${HOME}/.local/share"
  BIN="${HOME}/.local/bin"
  APP_DIR="${SHARE}/aidyship"
  install -d -m 0755 "${APP_DIR}/aidyship" "${BIN}" "${SHARE}/applications"
  install -m 0644 "$ROOT/packaging/aidyship/aidyship/"*.py "${APP_DIR}/aidyship/"
  install -m 0644 "$ROOT/packaging/aidyship/README.md" "${APP_DIR}/README.md"
  cat >"${BIN}/aidyship" <<EOF
#!/bin/sh
set -eu
export PYTHONPATH=${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}
exec python3 -m aidyship "\$@"
EOF
  chmod 0755 "${BIN}/aidyship"
  # Desktop entry pointing at the user wrapper.
  sed "s|/usr/local/bin/aidyship|${BIN}/aidyship|g" \
    "$ROOT/packaging/aidyship/aidyship.desktop" >"${SHARE}/applications/aidyship.desktop"
  install_icons "${SHARE}"
  if [[ -f "$ROOT/packaging/aidyship/aidyship.png" ]]; then
    install -D -m 0644 "$ROOT/packaging/aidyship/aidyship.png" "${SHARE}/pixmaps/aidyship.png"
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "${SHARE}/icons/hicolor" >/dev/null 2>&1 || true
  fi
  update-desktop-database "${SHARE}/applications" >/dev/null 2>&1 || true
  echo "AidyShip instalado en el usuario. Asegura PATH con ~/.local/bin y ejecuta: aidyship ui"
  exit 0
fi

sudo install -d -m 0755 /opt/aidyc/aidyship/aidyship
sudo install -m 0644 "$ROOT/packaging/aidyship/aidyship/"*.py /opt/aidyc/aidyship/aidyship/
sudo install -m 0644 "$ROOT/packaging/aidyship/README.md" /opt/aidyc/aidyship/README.md
sudo install -m 0755 "$ROOT/packaging/aidyship/aidyship-wrapper" /usr/local/bin/aidyship
sudo install -m 0644 "$ROOT/packaging/aidyship/aidyship.desktop" /usr/share/applications/aidyship.desktop
install -d "${HOME}/.local/share/applications"
install -m 0644 "$ROOT/packaging/aidyship/aidyship.desktop" "${HOME}/.local/share/applications/aidyship.desktop"

for icon_size in 16 24 32 48 64 128 256 512; do
  if [[ -f "$ROOT/packaging/aidyship/icons/aidyship-${icon_size}.png" ]]; then
    sudo install -D -m 0644 \
      "$ROOT/packaging/aidyship/icons/aidyship-${icon_size}.png" \
      "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyship.png"
    install -D -m 0644 \
      "$ROOT/packaging/aidyship/icons/aidyship-${icon_size}.png" \
      "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyship.png"
  fi
done
if [[ -f "$ROOT/packaging/aidyship/aidyship.png" ]]; then
  sudo install -D -m 0644 "$ROOT/packaging/aidyship/aidyship.png" /usr/share/pixmaps/aidyship.png
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
  gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
echo "AidyShip actualizado. Abre el menú o ejecuta: aidyship ui"
