#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sudo install -d -m 0755 /opt/aidyc/aidylink/aidylink
sudo install -m 0644 "$ROOT/packaging/aidylink/aidylink/"*.py /opt/aidyc/aidylink/aidylink/
sudo install -m 0644 "$ROOT/packaging/aidylink/README.md" /opt/aidyc/aidylink/README.md
sudo install -D -m 0644 "$ROOT/packaging/aidylink/aidylink.service" /usr/lib/systemd/user/aidylink.service
sudo install -D -m 0644 "$ROOT/packaging/aidylink/aidylink.timer" /usr/lib/systemd/user/aidylink.timer
sudo install -m 0755 "$ROOT/packaging/aidylink/aidylink-wrapper" /usr/local/bin/aidylink
sudo install -m 0644 "$ROOT/packaging/aidylink/aidylink.desktop" /usr/share/applications/aidychat.desktop
sudo rm -f /usr/share/applications/aidylink.desktop
install -m 0644 "$ROOT/packaging/aidylink/aidylink.desktop" "${HOME}/.local/share/applications/aidychat.desktop"
rm -f "${HOME}/.local/share/applications/aidylink.desktop"
sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
user_unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
wants_dir="${user_unit_dir}/default.target.wants"
install -d "${user_unit_dir}" "${wants_dir}"
install -m 0644 "$ROOT/packaging/aidylink/aidylink.service" "${user_unit_dir}/aidylink.service"
install -m 0644 "$ROOT/packaging/aidylink/aidylink.timer" "${user_unit_dir}/aidylink.timer"
rm -f "${wants_dir}/aidylink.service"
ln -sfn "${user_unit_dir}/aidylink.timer" "${wants_dir}/aidylink.timer"
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user enable --now aidylink.timer >/dev/null 2>&1 || true
if systemctl --user is-active --quiet aidylink.service; then
  systemctl --user restart aidylink.service >/dev/null 2>&1 || true
fi

# Logos AidyChat (ventana / barra).
sudo rm -f /usr/share/icons/hicolor/scalable/apps/aidychat.svg
for icon_size in 16 24 32 48 64 128 256 512; do
  if [[ -f "$ROOT/packaging/aidylink/icons/aidychat-${icon_size}.png" ]]; then
    sudo install -D -m 0644 \
      "$ROOT/packaging/aidylink/icons/aidychat-${icon_size}.png" \
      "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidychat.png"
    install -D -m 0644 \
      "$ROOT/packaging/aidylink/icons/aidychat-${icon_size}.png" \
      "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidychat.png"
  fi
done
if [[ -f "$ROOT/packaging/aidylink/aidychat.png" ]]; then
  sudo install -D -m 0644 "$ROOT/packaging/aidylink/aidychat.png" /usr/share/pixmaps/aidychat.png
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
  gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
echo "AidyChat actualizado. Solo debe aparecer AidyChat en el menú."
