#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sudo install -d -m 0755 /opt/aidyc/aidylink/aidylink
sudo install -m 0644 "$ROOT/packaging/aidylink/aidylink/"*.py /opt/aidyc/aidylink/aidylink/
sudo install -m 0644 "$ROOT/packaging/aidylink/README.md" /opt/aidyc/aidylink/README.md
sudo install -m 0755 "$ROOT/packaging/aidylink/aidylink-wrapper" /usr/local/bin/aidylink
sudo install -m 0644 "$ROOT/packaging/aidylink/aidylink.desktop" /usr/share/applications/aidychat.desktop
sudo rm -f /usr/share/applications/aidylink.desktop
install -m 0644 "$ROOT/packaging/aidylink/aidylink.desktop" "${HOME}/.local/share/applications/aidychat.desktop"
rm -f "${HOME}/.local/share/applications/aidylink.desktop"
sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user restart aidylink.service >/dev/null 2>&1 || true
echo "AidyChat actualizado. Solo debe aparecer AidyChat en el menú."
