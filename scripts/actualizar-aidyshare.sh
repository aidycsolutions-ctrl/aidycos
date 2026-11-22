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
    if [[ -f "$ROOT/packaging/aidyshare/icons/aidyshare-${icon_size}.png" ]]; then
      install -D -m 0644 \
        "$ROOT/packaging/aidyshare/icons/aidyshare-${icon_size}.png" \
        "${dest_root}/icons/hicolor/${icon_size}x${icon_size}/apps/aidyshare.png"
    fi
  done
}

if [[ "${USER_MODE}" == 1 ]]; then
  SHARE="${HOME}/.local/share"
  BIN="${HOME}/.local/bin"
  APP_DIR="${SHARE}/aidyshare"
  install -d -m 0755 "${APP_DIR}/aidyshare" "${BIN}" "${SHARE}/applications" "${SHARE}/pixmaps"
  install -m 0644 "$ROOT/packaging/aidyshare/aidyshare/"*.py "${APP_DIR}/aidyshare/"
  install -m 0644 "$ROOT/packaging/aidyshare/README.md" "${APP_DIR}/README.md"
  if [[ -f "$ROOT/packaging/aidyshare/aidyshare.png" ]]; then
    install -D -m 0644 "$ROOT/packaging/aidyshare/aidyshare.png" "${APP_DIR}/aidyshare.png"
    install -D -m 0644 "$ROOT/packaging/aidyshare/aidyshare.png" "${SHARE}/pixmaps/aidyshare.png"
  fi
  cat >"${BIN}/aidyshare" <<EOF
#!/bin/sh
set -eu
export PYTHONPATH=${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}
exec python3 -m aidyshare "\$@"
EOF
  chmod 0755 "${BIN}/aidyshare"
  install_icons "${SHARE}"
  # Absolute Icon= so docks/menus resolve it even before icon-theme cache catches up.
  icon_file="${SHARE}/icons/hicolor/256x256/apps/aidyshare.png"
  if [[ ! -f "${icon_file}" && -f "${APP_DIR}/aidyshare.png" ]]; then
    icon_file="${APP_DIR}/aidyshare.png"
  fi
  sed "s|/usr/local/bin/aidyshare|${BIN}/aidyshare|g" \
    "$ROOT/packaging/aidyshare/aidyshare.desktop" \
    | sed "s|^Icon=.*|Icon=${icon_file}|" \
    >"${SHARE}/applications/aidyshare.desktop"
  if [[ ! -f "${SHARE}/icons/hicolor/index.theme" ]]; then
    cat >"${SHARE}/icons/hicolor/index.theme" <<'EOF'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Directories=16x16/apps,24x24/apps,32x32/apps,48x48/apps,64x64/apps,128x128/apps,256x256/apps,512x512/apps

[16x16/apps]
Size=16
Context=Applications
Type=Fixed

[24x24/apps]
Size=24
Context=Applications
Type=Fixed

[32x32/apps]
Size=32
Context=Applications
Type=Fixed

[48x48/apps]
Size=48
Context=Applications
Type=Fixed

[64x64/apps]
Size=64
Context=Applications
Type=Fixed

[128x128/apps]
Size=128
Context=Applications
Type=Fixed

[256x256/apps]
Size=256
Context=Applications
Type=Fixed

[512x512/apps]
Size=512
Context=Applications
Type=Fixed
EOF
  fi
  rm -f "${SHARE}/icons/hicolor/icon-theme.cache" >/dev/null 2>&1 || true
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "${SHARE}/icons/hicolor" >/dev/null 2>&1 || true
  fi
  update-desktop-database "${SHARE}/applications" >/dev/null 2>&1 || true
  echo "AidyShare instalado en el usuario. Ejecuta: aidyshare ui"
  exit 0
fi

sudo install -d -m 0755 /opt/aidyc/aidyshare/aidyshare
sudo install -m 0644 "$ROOT/packaging/aidyshare/aidyshare/"*.py /opt/aidyc/aidyshare/aidyshare/
sudo install -m 0644 "$ROOT/packaging/aidyshare/README.md" /opt/aidyc/aidyshare/README.md
if [[ -f "$ROOT/packaging/aidyshare/aidyshare.png" ]]; then
  sudo install -D -m 0644 "$ROOT/packaging/aidyshare/aidyshare.png" /opt/aidyc/aidyshare/aidyshare.png
  sudo install -D -m 0644 "$ROOT/packaging/aidyshare/aidyshare.png" /usr/share/pixmaps/aidyshare.png
fi
sudo install -m 0755 "$ROOT/packaging/aidyshare/aidyshare-wrapper" /usr/local/bin/aidyshare
sudo install -m 0644 "$ROOT/packaging/aidyshare/aidyshare.desktop" /usr/share/applications/aidyshare.desktop
install -d "${HOME}/.local/share/applications"
install -m 0644 "$ROOT/packaging/aidyshare/aidyshare.desktop" "${HOME}/.local/share/applications/aidyshare.desktop"
for icon_size in 16 24 32 48 64 128 256 512; do
  if [[ -f "$ROOT/packaging/aidyshare/icons/aidyshare-${icon_size}.png" ]]; then
    sudo install -D -m 0644 \
      "$ROOT/packaging/aidyshare/icons/aidyshare-${icon_size}.png" \
      "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyshare.png"
    install -D -m 0644 \
      "$ROOT/packaging/aidyshare/icons/aidyshare-${icon_size}.png" \
      "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyshare.png"
  fi
done
echo "AidyShare actualizado. Ejecuta: aidyshare ui"
