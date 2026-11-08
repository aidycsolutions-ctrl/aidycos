#!/usr/bin/env bash
# Apply the initial Debian 13 profile used by AidyCOS (without live-image settings).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) echo "Uso: install-debian-profile.sh [--dry-run]"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -r /etc/os-release ]]; then echo "No se puede identificar la distribución." >&2; exit 1; fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != debian || "${VERSION_ID:-}" != 13 ]]; then
  echo "Este perfil inicial requiere Debian 13. Detectado: ${PRETTY_NAME:-desconocido}." >&2
  exit 1
fi

if [[ "${DRY_RUN}" == 1 ]]; then
  cat <<'EOF'
Vista previa del perfil AidyCOS para Debian 13:
  * Verificar fuentes oficiales de Debian y añadir trixie-backports si faltan paquetes.
  * Instalar el conjunto de paquetes del perfil Hyprland/SDDM/Wayland/Jugoo.
  * Instalar la CLI AidyCOS y Jugoo para el usuario actual.
  * Seleccionar SDDM y habilitar el arranque gráfico.
  * Activar NumLock en la pantalla de acceso y en Hyprland.
  * Crear configuración inicial de Hyprland si no existe.
  * Ajustar GRUB a 2 segundos y programar cups-browsed después del entorno gráfico.
  * Mantener usuario, contraseña y autologin actuales; cambiar el gestor de sesión a SDDM y respaldar los ajustes Hyprland tocados.
No se hicieron cambios.
EOF
  exit 0
fi

if ! command -v sudo >/dev/null; then echo "Se requiere sudo para instalar paquetes del sistema." >&2; exit 1; fi
sudo -v

APT_SOURCES_DIR=/etc/apt/sources.list.d
STANDARD_SOURCE="${APT_SOURCES_DIR}/aidycos-debian.sources"
BACKPORT_SOURCE="${APT_SOURCES_DIR}/aidycos-backports.sources"

apt_has_candidate() {
  apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ { if ($2 != "(none)") found=1 } END { exit !found }'
}

ensure_source() {
  local path="$1" content="$2"
  if [[ -e "${path}" ]]; then
    echo "El archivo ${path} ya existe, pero los paquetes requeridos siguen sin candidato APT. No se modificó; revisa ese archivo." >&2
    exit 1
  fi
  printf '%s\n' "${content}" | sudo tee "${path}" >/dev/null
  echo "Fuente APT de AidyCOS añadida: ${path}"
}

sudo apt-get update
if ! apt_has_candidate python3-venv; then
  ensure_source "${STANDARD_SOURCE}" 'Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg'
fi
if ! apt_has_candidate hyprland || ! apt_has_candidate xdg-desktop-portal-hyprland; then
  ensure_source "${BACKPORT_SOURCE}" 'Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg'
fi
sudo apt-get update
if ! apt_has_candidate python3-venv; then
  echo "APT aún no encuentra python3-venv. Revisa la conectividad y las fuentes de Debian 13." >&2
  exit 1
fi
if ! apt_has_candidate hyprland || ! apt_has_candidate xdg-desktop-portal-hyprland; then
  echo "APT aún no encuentra Hyprland en trixie-backports. Revisa las fuentes de Debian 13." >&2
  exit 1
fi

BOOTSTRAP=(ca-certificates curl git python3 python3-pip python3-venv python3-setuptools)
sudo apt-get install -y --no-install-recommends "${BOOTSTRAP[@]}"

"${ROOT}/scripts/install-local.sh"
"${HOME}/.local/bin/aidycos" install aidyc-desktop --apply
sudo apt-get install -y --no-install-recommends -t trixie-backports \
  hyprland xdg-desktop-portal-hyprland hyprland-guiutils

install_jugoo() {
  local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
  local jugoo_dir="${config_home}/jugoo"
  mkdir -p "${config_home}"
  if [[ ! -e "${jugoo_dir}" ]]; then
    git clone --depth 1 https://github.com/aidycsolutions-ctrl/jugoo.git "${jugoo_dir}"
  elif [[ ! -d "${jugoo_dir}/.git" || ! -f "${jugoo_dir}/shell/__main__.py" ]]; then
    echo "${jugoo_dir} existe, pero no parece ser un checkout compatible de Jugoo. Se conserva; revisa esa ruta." >&2
    return 1
  fi
  (cd "${jugoo_dir}" && python3 -m shell --install)
}
install_jugoo

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
HYPR_DIR="${CONFIG_HOME}/hypr"
HYPR_CONF="${HYPR_DIR}/hyprland.conf"
HYPR_AIDYCOS_CONF="${HYPR_DIR}/aidycos.conf"
mkdir -p "${HYPR_DIR}"
if [[ ! -e "${HYPR_AIDYCOS_CONF}" ]]; then
  cat >"${HYPR_AIDYCOS_CONF}" <<'EOF'
# AidyCOS keyboard defaults.
input {
    numlock_by_default = true
}
EOF
elif ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}"; then
  cp -a "${HYPR_AIDYCOS_CONF}" "${HYPR_AIDYCOS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  cat >>"${HYPR_AIDYCOS_CONF}" <<'EOF'

input {
    numlock_by_default = true
}
EOF
fi

if [[ ! -e "${HYPR_CONF}" ]]; then
  cat >"${HYPR_CONF}" <<'EOF'
# AidyCOS: configuración base compatible con el perfil inicial.
monitor = , preferred, auto, 1
input {
    kb_layout = latam
    numlock_by_default = true
}
general {
    border_size = 2
    gaps_in = 4
    gaps_out = 8
}
decoration {
    rounding = 8
}
exec-once = ~/.local/bin/jugoo
bind = SUPER, Q, killactive
bind = SUPER, RETURN, exec, foot
bind = SUPER, M, exit
EOF
  echo "Configuración base creada en ${HYPR_CONF}"
else
  changed=0
  if ! grep -qE '^[[:space:]]*source[[:space:]]*=.*aidycos\.conf' "${HYPR_CONF}" \
     && ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_CONF}"; then
    changed=1
  fi
  if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*jugoo' "${HYPR_CONF}"; then
    changed=1
  fi
  if [[ "${changed}" == 1 ]]; then
    backup="${HYPR_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    cp -a "${HYPR_CONF}" "${backup}"
    if ! grep -qE '^[[:space:]]*source[[:space:]]*=.*aidycos\.conf' "${HYPR_CONF}"; then
      printf '\n# AidyCOS keyboard defaults.\nsource = ~/.config/hypr/aidycos.conf\n' >>"${HYPR_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*jugoo' "${HYPR_CONF}"; then
      cat >>"${HYPR_CONF}" <<'EOF'

# AidyCOS: iniciar Jugoo al entrar en Hyprland.
exec-once = ~/.local/bin/jugoo
EOF
    fi
    echo "Se agregaron los ajustes AidyCOS; respaldo previo: ${backup}"
  fi
fi

apply_grub_profile() {
  local grub=/etc/default/grub tmp
  if [[ ! -f "${grub}" ]] || ! command -v update-grub >/dev/null; then
    echo "GRUB no está instalado; se omite su perfil."
    return
  fi
  if sudo grep -qE '^GRUB_TIMEOUT=2$' "${grub}" && sudo grep -qE '^GRUB_TIMEOUT_STYLE=menu$' "${grub}"; then
    echo "GRUB ya tiene el perfil AidyCOS."
    return
  fi
  sudo cp -a "${grub}" "${grub}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  tmp="$(mktemp)"
  sudo awk '
    BEGIN { timeout=0; style=0 }
    /^GRUB_TIMEOUT=/ { print "GRUB_TIMEOUT=2"; timeout=1; next }
    /^GRUB_TIMEOUT_STYLE=/ { print "GRUB_TIMEOUT_STYLE=menu"; style=1; next }
    { print }
    END { if (!timeout) print "GRUB_TIMEOUT=2"; if (!style) print "GRUB_TIMEOUT_STYLE=menu" }
  ' "${grub}" >"${tmp}"
  sudo install -m 0644 "${tmp}" "${grub}"
  rm -f "${tmp}"
  sudo update-grub
}
apply_grub_profile

if command -v systemctl >/dev/null && systemctl list-unit-files cups-browsed.service >/dev/null 2>&1; then
  override=/etc/systemd/system/cups-browsed.service.d/aidycos.conf
  if [[ ! -e "${override}" ]]; then
    sudo install -d /etc/systemd/system/cups-browsed.service.d
    printf '[Unit]\nAfter=graphical.target\n' | sudo tee "${override}" >/dev/null
  elif ! sudo grep -q '^After=graphical.target$' "${override}"; then
    echo "Se conserva el override existente de cups-browsed: ${override}"
    override=
  fi
  if [[ -n "${override}" ]]; then
    sudo systemctl daemon-reload
    sudo systemctl disable cups-browsed.service >/dev/null 2>&1 || true
    sudo systemctl add-wants graphical.target cups-browsed.service
    echo "cups-browsed quedó programado después del entorno gráfico."
  fi
fi

configure_login() {
  local dm_link=/etc/systemd/system/display-manager.service current_target old_unit
  if [[ -e "${dm_link}" && ! -L "${dm_link}" ]]; then
    echo "${dm_link} es un archivo regular; se conserva. No se puede seleccionar SDDM automáticamente." >&2
    return 1
  fi
  if [[ -L "${dm_link}" ]]; then
    current_target="$(readlink "${dm_link}")"
    if [[ "${current_target}" != *sddm.service ]]; then
      old_unit="$(basename "${current_target}")"
      sudo install -d /var/lib/aidycos
      if [[ ! -e /var/lib/aidycos/previous-display-manager ]]; then
        printf '%s\n' "${old_unit}" | sudo tee /var/lib/aidycos/previous-display-manager >/dev/null
      fi
      sudo systemctl disable "${old_unit}" >/dev/null 2>&1 || true
      sudo rm -f "${dm_link}"
    fi
  fi
  sudo systemctl enable sddm.service
  if [[ "$(systemctl get-default)" != graphical.target ]]; then
    sudo systemctl set-default graphical.target
  fi
  sudo install -d /etc/sddm.conf.d
  local sddm_conf=/etc/sddm.conf.d/90-aidycos.conf
  if [[ ! -e "${sddm_conf}" ]]; then
    printf '[General]\nNumlock=on\n' | sudo tee "${sddm_conf}" >/dev/null
  elif ! sudo grep -qiE '^Numlock[[:space:]]*=[[:space:]]*on$' "${sddm_conf}"; then
    echo "Se conserva ${sddm_conf}; configura Numlock=on manualmente si quieres NumLock en la pantalla de acceso."
  fi
  echo "SDDM quedó seleccionado y NumLock se activa en la pantalla de acceso."
}
configure_login

cat <<EOF

AidyCOS quedó aplicado sobre Debian 13.
Reinicia el equipo. En SDDM selecciona la sesión Hyprland la primera vez; luego se recordará.
NumLock queda activo en SDDM y Hyprland. Si se modificó tu configuración de Hyprland, revisa el respaldo indicado arriba.
EOF
