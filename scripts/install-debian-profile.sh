#!/usr/bin/env bash
# Apply the initial Debian 13 profile used by AidyCOS (without live-image settings).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
NO_REBOOT=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-reboot) NO_REBOOT=1 ;;
    -h|--help) echo "Uso: install-debian-profile.sh [--dry-run] [--no-reboot]"; exit 0 ;;
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
  * Configurar el comprobador diario de actualizaciones de AidyCOS, con confirmación antes de aplicar.
  * Quitar la versión anterior del paquete AidyC si está instalada (conservar sus datos).
  * Instalar AidyChat nativo, icono/acceso de escritorio y daemon de usuario para notificaciones.
  * Habilitar NetworkManager y UPower para los indicadores de Wi-Fi y batería de Jugoo.
  * Instalar los ajustes de Jugoo para el control de volumen y los iconos del escritorio.
  * Instalar las acciones de Hyprland para mover, minimizar y restaurar ventanas.
  * Configurar GRUB sin menú prolongado, el splash de Plymouth con logo y el tema de inicio de sesión SDDM.
  * Seleccionar SDDM y habilitar el arranque gráfico.
  * Activar NumLock en la pantalla de acceso y en Hyprland.
  * Crear configuración inicial de Hyprland si no existe.
  * Ocultar GRUB y los mensajes de arranque; mostrar el logo en Plymouth y SDDM.
  * Retrasar cups-browsed hasta el entorno gráfico.
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
  # apt-cache localizes its headings (for example, "Candidato:" in Spanish).
  # Force the stable English field name so source detection works on every locale.
  LC_ALL=C apt-cache policy "$1" 2>/dev/null \
    | awk '/Candidate:/ { if ($2 != "(none)") found=1 } END { exit !found }'
}

apt_has_suite() {
  local package="$1" suite="$2"
  # A package can look available only because it is already installed. Verify
  # that APT has an index entry from the suite needed by the profile.
  LC_ALL=C apt-cache policy "${package}" 2>/dev/null \
    | awk -v suite="${suite}/" 'index($0, suite) { found=1 } END { exit !found }'
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
if ! apt_has_suite python3-venv trixie || ! apt_has_suite libonnxruntime1.21 trixie; then
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
if ! apt_has_suite hyprland trixie-backports || ! apt_has_suite xdg-desktop-portal-hyprland trixie-backports; then
  ensure_source "${BACKPORT_SOURCE}" 'Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg'
fi
sudo apt-get update
if ! apt_has_suite python3-venv trixie || ! apt_has_candidate python3-venv; then
  echo "APT aún no encuentra python3-venv. Revisa la conectividad y las fuentes de Debian 13." >&2
  exit 1
fi
if ! apt_has_suite libonnxruntime1.21 trixie; then
  echo "APT no encuentra libonnxruntime1.21 en Debian 13, requerido por PipeWire de backports. Revisa las fuentes oficiales trixie/main." >&2
  exit 1
fi
if ! apt_has_suite hyprland trixie-backports || ! apt_has_suite xdg-desktop-portal-hyprland trixie-backports \
   || ! apt_has_candidate hyprland || ! apt_has_candidate xdg-desktop-portal-hyprland; then
  echo "APT aún no encuentra Hyprland en trixie-backports. Revisa las fuentes de Debian 13." >&2
  exit 1
fi

BOOTSTRAP=(ca-certificates curl git python3 python3-pip python3-venv python3-setuptools)
sudo apt-get install -y --no-install-recommends "${BOOTSTRAP[@]}"

"${ROOT}/scripts/install-local.sh"
"${HOME}/.local/bin/aidycos" install aidyc-desktop --apply
sudo apt-get install -y --no-install-recommends -t trixie-backports \
  hyprland xdg-desktop-portal-hyprland hyprland-guiutils
sudo apt-get install -y --no-install-recommends plymouth plymouth-themes

PLYMOUTH_DIR=/usr/share/plymouth/themes/aidycos
sudo install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" "${PLYMOUTH_DIR}/AidyCOS.png"
sudo install -m 0644 "${ROOT}/packaging/plymouth/aidycos.plymouth" "${PLYMOUTH_DIR}/aidycos.plymouth"
sudo install -m 0644 "${ROOT}/packaging/plymouth/aidycos.script" "${PLYMOUTH_DIR}/aidycos.script"
sudo install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" /usr/share/backgrounds/aidycos.png
sudo plymouth-set-default-theme aidycos
sudo update-initramfs -u -k all

SDDM_THEME_DIR=/usr/share/sddm/themes/aidycos
sudo install -d -m 0755 "${SDDM_THEME_DIR}"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/Main.qml" "${SDDM_THEME_DIR}/Main.qml"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/metadata.desktop" "${SDDM_THEME_DIR}/metadata.desktop"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/theme.conf" "${SDDM_THEME_DIR}/theme.conf"
sudo install -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" "${SDDM_THEME_DIR}/aidycos.png"

install_jugoo() {
  local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
  local jugoo_dir="${config_home}/jugoo"
  mkdir -p "${config_home}"
  if [[ ! -e "${jugoo_dir}" ]]; then
    git clone --depth 1 https://github.com/aidycsolutions-ctrl/jugoo.git "${jugoo_dir}"
  elif [[ ! -d "${jugoo_dir}/.git" || ! -f "${jugoo_dir}/shell/__main__.py" ]]; then
    echo "${jugoo_dir} existe, pero no parece ser un checkout compatible de Jugoo. Se conserva; revisa esa ruta." >&2
    return 1
  else
    if [[ -z "$(git -C "${jugoo_dir}" status --porcelain)" ]]; then
      git -C "${jugoo_dir}" pull --ff-only
    else
      echo "Jugoo tiene cambios locales; se conservarán y no se actualizará automáticamente." >&2
    fi
  fi
  python3 "${ROOT}/packaging/jugoo-overlay/install.py" "${jugoo_dir}"
  install -D -m 0644 "${ROOT}/packaging/jugoo-overlay/aidyc.desktop" "${HOME}/.local/share/applications/aidyc.desktop"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
  fi
  (cd "${jugoo_dir}" && python3 -m shell --install)
}
install_jugoo

# Jugoo's network and battery indicators use NetworkManager and UPower.
sudo systemctl enable --now NetworkManager.service
sudo systemctl enable --now upower.service

# Remove the previously installed, broken AidyC package once, on the first
# successful profile apply. Later AidyCOS updates must not remove AidyC again.
# `remove` leaves the user's application data in ~/.local/share/AidyC intact.
AIDYC_CLEANUP_MARKER=/var/lib/aidycos/legacy-aidyc-cleaned
if ! sudo test -e "${AIDYC_CLEANUP_MARKER}"; then
  if dpkg-query -W -f='${db:Status-Status}' aidyc 2>/dev/null | grep -qx 'installed'; then
    sudo apt-get remove -y aidyc
    echo "Se quitó el paquete AidyC anterior; sus datos de usuario se conservaron."
  fi
  sudo install -D -m 0644 /dev/null "${AIDYC_CLEANUP_MARKER}"
fi

install_aidylink() {
  local aidylink_dir=/opt/aidyc/aidylink
  local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
  local desktop_dir="${HOME}/.local/share/applications"
  local desktop_entry="${ROOT}/packaging/aidylink/aidylink.desktop"
  local user_desktop=""
  local service_dir="${config_home}/systemd/user"
  sudo install -d -m 0755 "${aidylink_dir}/aidylink" /usr/local/bin /usr/share/applications
  sudo install -m 0644 "${ROOT}/packaging/aidylink/aidylink/"*.py "${aidylink_dir}/aidylink/"
  sudo install -m 0644 "${ROOT}/packaging/aidylink/README.md" "${aidylink_dir}/README.md"
  sudo install -m 0755 "${ROOT}/packaging/aidylink/aidylink-wrapper" /usr/local/bin/aidylink
  sudo install -m 0644 "${desktop_entry}" /usr/share/applications/aidychat.desktop
  sudo install -D -m 0644 "${ROOT}/packaging/aidylink/aidychat.svg" /usr/share/icons/hicolor/scalable/apps/aidychat.svg
  install -d "${desktop_dir}" "${service_dir}"
  install -m 0644 "${desktop_entry}" "${desktop_dir}/aidychat.desktop"
  install -m 0644 "${ROOT}/packaging/aidylink/aidylink.service" "${service_dir}/aidylink.service"
  if command -v xdg-user-dir >/dev/null 2>&1; then
    user_desktop="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -z "${user_desktop}" || "${user_desktop}" == "${HOME}" ]]; then
    user_desktop="${HOME}/Desktop"
  fi
  mkdir -p "${user_desktop}"
  install -m 0755 "${desktop_entry}" "${user_desktop}/AidyChat.desktop"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
  fi
  echo "AidyChat instalado. Abre el acceso del escritorio y ejecuta aidylink init --name NOMBRE --team EQUIPO para activar el daemon y las notificaciones en segundo plano."
}
install_aidylink

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
HYPR_DIR="${CONFIG_HOME}/hypr"
HYPR_CONF="${HYPR_DIR}/hyprland.conf"
HYPR_AIDYCOS_CONF="${HYPR_DIR}/aidycos.conf"
HYPR_WINDOWS_CONF="${HYPR_DIR}/config/jugoo_ventanas.conf"
mkdir -p "${HYPR_DIR}" "${HYPR_DIR}/config" "${HYPR_DIR}/scripts"
install -m 0755 "${ROOT}/packaging/hyprland/scripts/ventanas" "${HYPR_DIR}/scripts/ventanas"
install -m 0644 "${ROOT}/packaging/hyprland/scripts/ventanas.py" "${HYPR_DIR}/scripts/ventanas.py"
if [[ ! -e "${HYPR_WINDOWS_CONF}" ]] || ! cmp -s "${ROOT}/packaging/hyprland/config/jugoo_ventanas.conf" "${HYPR_WINDOWS_CONF}"; then
  if [[ -e "${HYPR_WINDOWS_CONF}" ]]; then
    cp -a "${HYPR_WINDOWS_CONF}" "${HYPR_WINDOWS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  fi
  install -m 0644 "${ROOT}/packaging/hyprland/config/jugoo_ventanas.conf" "${HYPR_WINDOWS_CONF}"
fi
sudo install -m 0755 "${ROOT}/packaging/hyprland/aidycos-prefer-external-display" /usr/local/bin/aidycos-prefer-external-display
if [[ ! -e "${HYPR_AIDYCOS_CONF}" ]]; then
  cat >"${HYPR_AIDYCOS_CONF}" <<'EOF'
# AidyCOS keyboard and Jugoo defaults.
input {
    numlock_by_default = true
}
bind = SUPER, SPACE, exec, jugoo action launcher
bind = CTRL, SPACE, exec, jugoo action launcher
bind = SUPER, C, exec, aidylink ui
bind = SUPER SHIFT, U, exec, aidycos-update --check
source = ~/.config/hypr/config/jugoo_ventanas.conf
exec-once = /usr/local/bin/aidycos-prefer-external-display
EOF
else
  missing=0
  grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'source = ~/.config/hypr/config/jugoo_ventanas.conf' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'exec-once = /usr/local/bin/aidycos-prefer-external-display' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'bind = SUPER SHIFT, U, exec, aidycos-update --check' "${HYPR_AIDYCOS_CONF}" || missing=1
  if [[ "${missing}" == 1 ]]; then
    cp -a "${HYPR_AIDYCOS_CONF}" "${HYPR_AIDYCOS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    if ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}"; then
      cat >>"${HYPR_AIDYCOS_CONF}" <<'EOF'

input {
    numlock_by_default = true
}
EOF
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}"; then
      printf '\nbind = SUPER, SPACE, exec, jugoo action launcher\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}"; then
      printf 'bind = CTRL, SPACE, exec, jugoo action launcher\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui' "${HYPR_AIDYCOS_CONF}"; then
      printf 'bind = SUPER, C, exec, aidylink ui\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'source = ~/.config/hypr/config/jugoo_ventanas.conf' "${HYPR_AIDYCOS_CONF}"; then
      printf 'source = ~/.config/hypr/config/jugoo_ventanas.conf\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'exec-once = /usr/local/bin/aidycos-prefer-external-display' "${HYPR_AIDYCOS_CONF}"; then
      printf 'exec-once = /usr/local/bin/aidycos-prefer-external-display\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'bind = SUPER SHIFT, U, exec, aidycos-update --check' "${HYPR_AIDYCOS_CONF}"; then
      printf 'bind = SUPER SHIFT, U, exec, aidycos-update --check\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
  fi
fi

if [[ ! -e "${HYPR_CONF}" ]]; then
  cat >"${HYPR_CONF}" <<'EOF'
# AidyCOS: configuración base compatible con el perfil inicial.
source = ~/.config/hypr/aidycos.conf
monitor = , preferred, auto, 1
input {
    kb_layout = latam
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
  if ! grep -qE '^[[:space:]]*source[[:space:]]*=.*aidycos\.conf' "${HYPR_CONF}"; then
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
  sudo install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" /boot/grub/AidyCOS.png
  if sudo grep -qE '^GRUB_TIMEOUT=1$' "${grub}" \
     && sudo grep -qE '^GRUB_TIMEOUT_STYLE=hidden$' "${grub}" \
     && sudo grep -qF 'GRUB_BACKGROUND="/boot/grub/AidyCOS.png"' "${grub}" \
     && sudo grep -qE '^GRUB_GFXMODE=auto$' "${grub}" \
     && sudo grep -qE '^GRUB_GFXPAYLOAD_LINUX=keep$' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*quiet' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*splash' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*loglevel=3' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*systemd.show_status=false' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*vt.global_cursor_default=0' "${grub}" \
     && sudo grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*udev.log_level=3' "${grub}" \
     && { [[ ! -f /etc/grub.d/10_linux ]] || sudo grep -q '^quiet_boot="1"$' /etc/grub.d/10_linux; }; then
    echo "GRUB ya tiene el perfil AidyCOS."
    return
  fi
  sudo cp -a "${grub}" "${grub}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  tmp="$(mktemp)"
  sudo awk '
    BEGIN { timeout=0; style=0; background=0; gfxmode=0; payload=0 }
    /^GRUB_TIMEOUT=/ { print "GRUB_TIMEOUT=1"; timeout=1; next }
    /^GRUB_TIMEOUT_STYLE=/ { print "GRUB_TIMEOUT_STYLE=hidden"; style=1; next }
    /^GRUB_BACKGROUND=/ { print "GRUB_BACKGROUND=\"/boot/grub/AidyCOS.png\""; background=1; next }
    /^GRUB_GFXMODE=/ { print "GRUB_GFXMODE=auto"; gfxmode=1; next }
    /^GRUB_GFXPAYLOAD_LINUX=/ { print "GRUB_GFXPAYLOAD_LINUX=keep"; payload=1; next }
    { print }
    END {
      if (!timeout) print "GRUB_TIMEOUT=1"
      if (!style) print "GRUB_TIMEOUT_STYLE=hidden"
      if (!background) print "GRUB_BACKGROUND=\"/boot/grub/AidyCOS.png\""
      if (!gfxmode) print "GRUB_GFXMODE=auto"
      if (!payload) print "GRUB_GFXPAYLOAD_LINUX=keep"
    }
  ' "${grub}" >"${tmp}"
  sudo install -m 0644 "${tmp}" "${grub}"
  rm -f "${tmp}"
  sudo python3 - <<'PY'
from pathlib import Path
import re

path = Path('/etc/default/grub')
lines = path.read_text().splitlines()
prefix = 'GRUB_CMDLINE_LINUX_DEFAULT='
for index, line in enumerate(lines):
    if line.startswith(prefix):
        match = re.fullmatch(r"GRUB_CMDLINE_LINUX_DEFAULT=([\"'])(.*)\1", line)
        if match:
            options = match.group(2).split()
            for option in (
                'quiet', 'splash', 'loglevel=3', 'systemd.show_status=false',
                'rd.systemd.show_status=false', 'vt.global_cursor_default=0',
                'udev.log_level=3', 'rd.udev.log_level=3',
            ):
                if option not in options:
                    options.append(option)
            lines[index] = prefix + match.group(1) + ' '.join(options) + match.group(1)
        break
else:
    lines.append(prefix + '"quiet splash loglevel=3 systemd.show_status=false rd.systemd.show_status=false vt.global_cursor_default=0 udev.log_level=3 rd.udev.log_level=3"')
path.write_text('\n'.join(lines) + '\n')
PY
  local linux_generator=/etc/grub.d/10_linux
  if [[ -f "${linux_generator}" ]] && sudo grep -q '^quiet_boot="0"$' "${linux_generator}"; then
    sudo cp -a "${linux_generator}" "${linux_generator}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sudo sed -i 's/^quiet_boot="0"$/quiet_boot="1"/' "${linux_generator}"
  fi
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
  local sddm_conf=/etc/sddm.conf.d/99-aidycos.conf
  local sddm_needs_update=0
  if [[ ! -e "${sddm_conf}" ]] || ! sudo grep -qF 'Current=aidycos' "${sddm_conf}" \
     || ! sudo grep -qiE '^Numlock[[:space:]]*=[[:space:]]*on$' "${sddm_conf}" \
     || ! sudo grep -q '^InputMethod=$' "${sddm_conf}"; then
    sddm_needs_update=1
  fi
  if [[ -e "${sddm_conf}" && "${sddm_needs_update}" == 1 ]]; then
    sudo cp -a "${sddm_conf}" "${sddm_conf}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    echo "Se respaldó la configuración SDDM existente: ${sddm_conf}"
  fi
  if [[ "${sddm_needs_update}" == 1 ]]; then
    printf '[General]\nNumlock=on\nInputMethod=\n\n[Theme]\nCurrent=aidycos\n' | sudo tee "${sddm_conf}" >/dev/null
  fi
  echo "SDDM usa el tema AidyCOS con el logo y NumLock activo."
}
configure_login

# Start the daily GitHub check only after the full profile install is complete.
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user enable --now aidycos-update-check.timer >/dev/null 2>&1 || true

cat <<EOF

AidyCOS quedó aplicado sobre Debian 13.
GRUB queda oculto con espera breve; Plymouth muestra el logo AidyCOS y SDDM presenta la pantalla de acceso personalizada.
En SDDM selecciona la sesión Hyprland la primera vez; luego se recordará. NumLock queda activo en SDDM y Hyprland. Si se modificó tu configuración de Hyprland, revisa el respaldo indicado arriba.
EOF

if [[ "${NO_REBOOT}" == 1 ]]; then
  echo "Reinicio omitido por --no-reboot."
  exit 0
fi

echo "La instalación terminó correctamente. El equipo se reiniciará en 15 segundos; pulsa Ctrl+C para cancelar."
sleep 15
sudo systemctl reboot
