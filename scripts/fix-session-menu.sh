#!/usr/bin/env bash
# Fix stuck Alt+F4 session menu (sticky dismiss) and install Cancel / Esc.
# Requires sudo once to write /opt/aidyc/jugoo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-/opt/aidyc/jugoo}"

if [[ ! -d "${TARGET}/shell" ]]; then
  echo "No se encontró Jugoo en ${TARGET}" >&2
  exit 1
fi

sudo python3 - <<PY
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location(
    "aidycos_jugoo_install",
    "${ROOT}/packaging/jugoo-overlay/install.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
root = Path("${TARGET}")
mod.install_session_menu_keyboard_focus(root)
text = (root / "shell/widgets/barra/power.py").read_text(encoding="utf-8")
popup = (root / "shell/popup_handle.py").read_text(encoding="utf-8")
assert "Cancelar" in text, "falta botón Cancelar"
assert "arm_keyboard_open_grace" in popup, "falta gracia de teclado"
print("Menú de sesión actualizado en", root)
PY

# Restart Jugoo so the new menu code loads.
if command -v jugoo >/dev/null 2>&1; then
  jugoo action relaunch >/dev/null 2>&1 || jugoo action restart >/dev/null 2>&1 || true
fi
# Fallback: kill the boot process; Hyprland exec-once / user service respawns it.
pkill -f 'jugoo_aidycos_boot.py' 2>/dev/null || true
pkill -f '/opt/aidyc/jugoo' 2>/dev/null || true
sleep 1
if ! pgrep -f 'jugoo_aidycos_boot.py' >/dev/null 2>&1; then
  nohup /home/angeljoc/.local/bin/jugoo >/dev/null 2>&1 &
  disown || true
fi
echo "Listo: Alt+F4 → Cancelar / Esc / clic fuera cierra el menú."
