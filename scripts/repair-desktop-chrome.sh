#!/usr/bin/env bash
# Repair title-bar buttons, Windows-like snap binds, and wallpaper backend on a
# live AidyCOS session (especially test laptops where hyprbars failed to load).
#
#   bash scripts/repair-desktop-chrome.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HYPR_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"

echo "Reparando chrome de ventanas AidyCOS…"
echo "======================================"

if ! command -v swaybg >/dev/null 2>&1; then
  echo "• instalando swaybg (fondo de escritorio)"
  sudo apt-get install -y --no-install-recommends swaybg
fi

plugin_ok=0
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
  if hyprctl plugin list 2>/dev/null | grep -qi '^Plugin hyprbars'; then
    plugin_ok=1
  fi
fi
if [[ "${plugin_ok}" == 1 && -f "${HOME}/.local/lib/jugoo/hyprbars.so" ]]; then
  echo "• hyprbars ya cargado; solo se refresca la configuración"
  bash "${ROOT}/packaging/hyprland/setup-hyprbars.sh"
else
  echo "• recompilando / recargando hyprbars"
  HYPRBARS_FORCE=1 bash "${ROOT}/packaging/hyprland/setup-hyprbars.sh"
fi

mkdir -p "${HYPR_HOME}/config" "${HYPR_HOME}/scripts"
install -m 0644 "${ROOT}/packaging/hyprland/config/jugoo_ventanas.conf" \
  "${HYPR_HOME}/config/jugoo_ventanas.conf"
install -m 0755 "${ROOT}/packaging/hyprland/scripts/ventanas" "${HYPR_HOME}/scripts/ventanas"
install -m 0644 "${ROOT}/packaging/hyprland/scripts/ventanas.py" "${HYPR_HOME}/scripts/ventanas.py"
install -m 0644 "${ROOT}/packaging/hyprland/scripts/decoraciones.py" "${HYPR_HOME}/scripts/decoraciones.py"

# Stop Super+Left/Right from fighting snap binds.
for hypr_file in "${HYPR_HOME}/hyprland.conf" "${HYPR_HOME}/aidycos.conf"; do
  if [[ -f "${hypr_file}" ]] && grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,' "${hypr_file}"; then
    cp -a "${hypr_file}" "${hypr_file}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,/d' "${hypr_file}"
    echo "• quitado Super+Left/Right=escritorio de ${hypr_file}"
  fi
done

# Drop stale CSD hide rules that can blank AidyChat title buttons.
CSD="${HYPR_HOME}/config/jugoo_hyprbars_csd.conf"
if [[ -f "${CSD}" ]] && grep -qiE 'class:.*(aidychat|aidylink)' "${CSD}"; then
  python3 - <<'PY' "${CSD}"
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
blocks = re.split(r"(?m)(?=^# class: )", text)
kept = []
for block in blocks:
    head = block.splitlines()[:1]
    name = ""
    if head and head[0].lower().startswith("# class:"):
        name = head[0].split(":", 1)[-1].strip().lower()
    if name in {"aidychat", "aidylink", "aidyc", "aidyship"}:
        continue
    kept.append(block)
path.write_text("".join(kept) if kept else "# Generado por ventanas. No editar.\n", encoding="utf-8")
print("• limpiadas reglas CSD que ocultaban AidyChat")
PY
fi

if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
  hyprctl reload >/dev/null || true
  sleep 1
  echo "• plugins:"
  hyprctl plugin list || true
  if ! hyprctl plugin list 2>/dev/null | grep -qi '^Plugin hyprbars'; then
    echo "ERROR: hyprbars sigue sin cargar. Revisa hyprland-dev y vuelve a intentar." >&2
    exit 1
  fi
  runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  pidfile="${runtime}/jugoo-ventanas.pid"
  if [[ -r "${pidfile}" ]]; then
    old="$(tr -d '[:space:]' <"${pidfile}" || true)"
    if [[ -n "${old}" ]]; then
      kill "${old}" 2>/dev/null || true
    fi
  fi
  rm -f "${runtime}/jugoo-ventanas.fifo" "${pidfile}"
  nohup python3 "${HYPR_HOME}/scripts/ventanas.py" daemon >/dev/null 2>&1 &
  echo "• daemon de ventanas reiniciado"
fi

if command -v jugoo >/dev/null 2>&1; then
  jugoo action restart >/dev/null 2>&1 || true
fi

cat <<'EOF'

Listo. Comprueba:
  1) Barra negra con botones amarillo/verde/rojo en ventanas (p.ej. AidyChat)
  2) Arrastrar desde la barra de título SIN Super; soltar en borde = dividir
  3) Super+Left / Super+Right = dividir (como Windows)
  4) Alt+F4 = menú de apagado que no se cierra solo
  5) Configuración → Tema → Escritorio = cambiar fondo (hace falta swaybg)

Si los botones no salen, cierra sesión Hyprland una vez e inicia de nuevo.
EOF
