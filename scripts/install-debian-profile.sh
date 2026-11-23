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
  * Preparar sudo/curl en instalaciones mínimas (sin escritorio) si hace falta.
  * Verificar fuentes oficiales de Debian y añadir trixie-backports si faltan paquetes.
  * Instalar el conjunto de paquetes del perfil Hyprland/SDDM/Wayland/Jugoo.
  * Instalar la CLI AidyCOS y Jugoo para el usuario actual.
  * Configurar el comprobador diario de actualizaciones de AidyCOS, con confirmación antes de aplicar.
  * Instalar el comando y acceso de menú para buscar actualizaciones Linux de AidyC.
  * Quitar la versión anterior del paquete AidyC si está instalada (conservar sus datos).
  * Instalar AidyChat nativo, icono/acceso de escritorio y daemon de usuario para notificaciones.
  * Instalar AidyShip (commit/push GitHub con gh por usuario), icono de menú y atajo Super+G.
  * Instalar AidyShare (respaldo a AidyCShare del negocio con login AidyC).
  * Habilitar NetworkManager, UPower y BlueZ para Wi-Fi, batería y Bluetooth de Jugoo.
  * Migrar Wi-Fi de ifupdown (instalador Debian) a NetworkManager para que Jugoo no lo vea como LAN.
  * Instalar librsvg2-common para que los iconos symbolic SVG de Adwaita no salgan como rectángulos.
  * Instalar los ajustes de Jugoo para volumen, fondo de escritorio, iconos y atajos.
  * Sembrar fondo AidyCOS e iconos del escritorio (AidyChat, Firefox, Archivos, Terminal, paquetes, OnlyOffice).
  * Instalar Firefox ESR como navegador por defecto del perfil.
  * Instalar Synaptic, Flatpak/Flathub y el agente Polkit para descargar OnlyOffice u otras apps.
  * Instalar udisks2/gvfs/gvfs-fuse/thunar-volman, activar automount y thunar --daemon para USB.
  * Unificar Descargas/Downloads (XDG) y refrescar Thunar al terminar descargas del navegador.
  * Instalar botones de cerrar, maximizar y minimizar, y atajos de Hyprland para ventanas y escritorios.
  * Configurar GRUB sin menú, modo gráfico con fallbacks y el splash de Plymouth con logo (apply-aidycos-boot.sh).
  * Preferir la resolución del monitor externo detectado para GRUB/Plymouth cuando exista.
  * Desactivar drop-ins legados de AidyC que vuelvan a mostrar texto de arranque.
  * Seleccionar SDDM y habilitar el arranque gráfico; logo y formulario de acceso en todas las pantallas.
  * Activar NumLock en la pantalla de acceso y en Hyprland (con refuerzo al entrar).
  * Tratar el Intro del teclado numérico (KP_Enter) como Enter.
  * Crear configuración inicial de Hyprland si no existe.
  * Ocultar GRUB y los mensajes de arranque; mostrar el logo en Plymouth y SDDM.
  * Retrasar cups-browsed hasta el entorno gráfico.
  * Instalar el gestor de impresoras y Alt+F4 para el menú de apagado.
  * Crear la cola raw Tickets cuando hay una térmica ESC/POS, para abrir el cajón.
  * Instalar el comando aidycos-cajon (abre la XPRINTER sin recompilar AidyC).
  * Mantener usuario, contraseña y autologin actuales; cambiar el gestor de sesión a SDDM y respaldar los ajustes Hyprland tocados.
  * Instalar el comando y acceso de menú «Quitar AidyCOS» para devolver el sistema anterior.
No se hicieron cambios.
EOF
  exit 0
fi

# Resolve the first interactive desktop user (uid >= 1000), preferring AIDYCOS_USER.
aidycos_target_user() {
  local candidate=""
  if [[ -n "${AIDYCOS_USER:-}" && "${AIDYCOS_USER}" != "root" ]]; then
    if getent passwd "${AIDYCOS_USER}" >/dev/null; then
      printf '%s\n' "${AIDYCOS_USER}"
      return 0
    fi
    echo "AIDYCOS_USER=${AIDYCOS_USER} no existe en el sistema." >&2
    return 1
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    printf '%s\n' "${SUDO_USER}"
    return 0
  fi
  candidate="$(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 && $1 != "nobody" { print $1; exit }')"
  if [[ -n "${candidate}" ]]; then
    printf '%s\n' "${candidate}"
    return 0
  fi
  return 1
}

aidycos_print_sudo_fix() {
  local user_name="$1"
  cat <<EOF >&2
Tu usuario «${user_name}» aún no puede usar sudo.

Como root, ejecuta exactamente esto (copia/pega):

  su -
  apt-get update
  apt-get install -y sudo curl ca-certificates
  usermod -aG sudo ${user_name}
  printf '%s\n' '%sudo ALL=(ALL:ALL) ALL' >/etc/sudoers.d/10-aidycos-sudo
  chmod 440 /etc/sudoers.d/10-aidycos-sudo
  exit
  reboot

Después entra otra vez como «${user_name}» y vuelve a lanzar el instalador.
EOF
}

aidycos_ensure_sudoers_group_rule() {
  local rule_file=/etc/sudoers.d/10-aidycos-sudo
  if [[ -e "${rule_file}" ]]; then
    return 0
  fi
  if grep -RqsE '^[[:space:]]*%sudo[[:space:]]+' /etc/sudoers /etc/sudoers.d 2>/dev/null; then
    return 0
  fi
  printf '%s\n' '%sudo ALL=(ALL:ALL) ALL' >"${rule_file}"
  chmod 440 "${rule_file}"
}

# Root on a minimal Debian: install sudo/curl, enable the user, and re-run as that user.
aidycos_bootstrap_from_root() {
  local target home_dir
  target="$(aidycos_target_user)" || {
    echo "No hay un usuario normal (uid >= 1000). Crea uno y vuelve a ejecutar, o usa AIDYCOS_USER=nombre." >&2
    exit 1
  }
  echo "Instalación mínima detectada (root). Preparando sudo para «${target}»…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends sudo curl ca-certificates
  getent group sudo >/dev/null || groupadd --system sudo
  usermod -aG sudo "${target}"
  aidycos_ensure_sudoers_group_rule
  home_dir="$(getent passwd "${target}" | cut -d: -f6)"
  if [[ -z "${home_dir}" || ! -d "${home_dir}" ]]; then
    echo "No se pudo resolver el HOME de «${target}»." >&2
    exit 1
  fi
  echo "Continuando la instalación como «${target}»…"
  exec runuser -u "${target}" -- \
    env HOME="${home_dir}" USER="${target}" LOGNAME="${target}" \
    bash "${ROOT}/scripts/install-debian-profile.sh" "$@"
}

aidycos_ensure_admin() {
  local me
  me="$(id -un)"

  if [[ "${EUID}" -eq 0 ]]; then
    aidycos_bootstrap_from_root "$@"
    exit 1
  fi

  if ! command -v sudo >/dev/null; then
    aidycos_print_sudo_fix "${me}"
    exit 1
  fi

  if sudo -n true 2>/dev/null; then
    return 0
  fi

  if sudo -v 2>/dev/null; then
    return 0
  fi

  aidycos_print_sudo_fix "${me}"
  exit 1
}

aidycos_ensure_admin "$@"

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

pkg_installed() {
  dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null | grep -qx installed
}

# Install only packages that are missing. Re-running apt-get install on a
# current profile prints "ya está en su versión más reciente" once per package
# and still solves the whole dependency tree.
apt_install_missing() {
  local suite=""
  if [[ "${1:-}" == "-t" ]]; then
    suite="$2"
    shift 2
  fi
  local -a missing=()
  local pkg
  for pkg in "$@"; do
    if ! pkg_installed "${pkg}"; then
      missing+=("${pkg}")
    fi
  done
  if ((${#missing[@]} == 0)); then
    return 0
  fi
  echo "Instalando paquetes que faltan: ${missing[*]}"
  if [[ -n "${suite}" ]]; then
    sudo apt-get install -y --no-install-recommends -t "${suite}" "${missing[@]}"
  else
    sudo apt-get install -y --no-install-recommends "${missing[@]}"
  fi
}

desktop_packages_present() {
  local line pkg
  line="$("${HOME}/.local/bin/aidycos" plan aidyc-desktop 2>/dev/null | sed -n 's/^Paquetes: //p' | head -n1)"
  [[ -n "${line}" && "${line}" != "ninguno" ]] || return 1
  for pkg in ${line}; do
    pkg_installed "${pkg}" || return 1
  done
}

# -f rebuilds every icon. On an update, refresh only if files are newer, and
# never rebuild Adwaita (the profile does not edit that theme).
refresh_icon_cache() {
  local as_root="$1" theme="$2"
  [[ -d "${theme}" ]] || return 0
  command -v gtk-update-icon-cache >/dev/null 2>&1 || return 0
  if [[ "${theme}" == */Adwaita && "${PROFILE_REFRESH:-0}" == 1 ]]; then
    return 0
  fi
  local -a cmd=(gtk-update-icon-cache)
  if [[ "${PROFILE_REFRESH:-0}" != 1 ]]; then
    cmd+=(-f)
  fi
  cmd+=("${theme}")
  if [[ "${as_root}" == sudo ]]; then
    sudo "${cmd[@]}" >/dev/null 2>&1 || true
  else
    "${cmd[@]}" >/dev/null 2>&1 || true
  fi
}

ensure_source() {
  local path="$1" content="$2"
  if [[ -e "${path}" ]]; then
    echo "El archivo ${path} ya existe, pero los paquetes requeridos siguen sin candidato APT. No se modificó; revisa ese archivo." >&2
    exit 1
  fi
  printf '%s\n' "${content}" | sudo tee "${path}" >/dev/null
  sudo install -d -m 0755 /var/lib/aidycos
  printf '%s\n' "${path}" | sudo tee -a /var/lib/aidycos/created-apt-sources >/dev/null
  echo "Fuente APT de AidyCOS añadida: ${path}"
}

# Re-applying an installed profile must not refresh APT twice and then
# reinstall every package that is already current.
PROFILE_REFRESH=0
if [[ -f /var/lib/aidycos/profile-installed ]]; then
  PROFILE_REFRESH=1
  echo "Actualizando AidyCOS: se omite lo que ya coincide."
fi

sources_changed=0
indexes_ready=0
if apt_has_suite python3-venv trixie && apt_has_suite libonnxruntime1.21 trixie \
   && apt_has_suite hyprland trixie-backports && apt_has_suite xdg-desktop-portal-hyprland trixie-backports; then
  indexes_ready=1
fi
if [[ "${PROFILE_REFRESH}" != 1 || "${indexes_ready}" != 1 ]]; then
  sudo apt-get update
fi
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
  sources_changed=1
fi
if ! apt_has_suite hyprland trixie-backports || ! apt_has_suite xdg-desktop-portal-hyprland trixie-backports; then
  ensure_source "${BACKPORT_SOURCE}" 'Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg'
  sources_changed=1
fi
if [[ "${sources_changed}" == 1 ]]; then
  sudo apt-get update
fi
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
apt_install_missing "${BOOTSTRAP[@]}"

"${ROOT}/scripts/install-local.sh"
if [[ "${PROFILE_REFRESH}" == 1 ]] && desktop_packages_present; then
  :
else
  "${HOME}/.local/bin/aidycos" install aidyc-desktop --apply
fi
apt_install_missing -t trixie-backports \
  hyprland xdg-desktop-portal-hyprland hyprland-guiutils hyprpolkitagent
apt_install_missing plymouth plymouth-themes
# Polkit agent is required so Synaptic/Flatpak can ask for the admin password in GUI.
POLKIT_AGENT=""
for candidate in \
  /usr/libexec/hyprpolkitagent \
  /usr/lib/x86_64-linux-gnu/libexec/hyprpolkitagent \
  /usr/bin/hyprpolkitagent
do
  if [[ -x "${candidate}" ]]; then
    POLKIT_AGENT="${candidate}"
    break
  fi
done
if [[ -z "${POLKIT_AGENT}" ]]; then
  if apt_has_candidate mate-polkit; then
    sudo apt-get install -y --no-install-recommends mate-polkit
  fi
  if [[ -x /usr/libexec/mate-polkit/polkit-mate-authentication-agent-1 ]]; then
    POLKIT_AGENT=/usr/libexec/mate-polkit/polkit-mate-authentication-agent-1
  fi
fi
if [[ -z "${POLKIT_AGENT}" ]]; then
  POLKIT_AGENT=/usr/libexec/hyprpolkitagent
fi

# Plymouth theme + quiet GRUB are applied together later by apply-aidycos-boot.sh
# (after packages/desktop pieces), so /usr/sbin tools are resolved by absolute path.

SDDM_THEME_DIR=/usr/share/sddm/themes/aidycos
sudo install -d -m 0755 "${SDDM_THEME_DIR}"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/Main.qml" "${SDDM_THEME_DIR}/Main.qml"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/metadata.desktop" "${SDDM_THEME_DIR}/metadata.desktop"
sudo install -m 0644 "${ROOT}/packaging/sddm/aidycos/theme.conf" "${SDDM_THEME_DIR}/theme.conf"
sudo install -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" "${SDDM_THEME_DIR}/aidycos.png"

install_jugoo() {
  local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
  local jugoo_dir=/opt/aidyc/jugoo
  local jugoo_source
  local staging_dir
  local source_dir="${AIDYCOS_JUGOO_SOURCE:-}"
  # Wallpaper + atajos + iconos viven en esta rama hasta fusionarse en main.
  local jugoo_ref="${AIDYCOS_JUGOO_REF:-feature/atajos-aidyc-escritorio}"
  local data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
  local jugoo_stamp_file="${data_home}/aidycos/jugoo-deploy-stamp"
  local jugoo_stamp=""
  local skip_jugoo_fetch=0

  # Same upstream commit and same overlay: do not clone, deploy, or reinstall.
  if [[ -z "${source_dir}" ]]; then
    local overlay_hash remote_sha
    overlay_hash="$(
      find "${ROOT}/packaging/jugoo-overlay" "${ROOT}/scripts/deploy-jugoo.py" \
        -type f ! -path '*/__pycache__/*' -print0 \
        | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
    )"
    remote_sha="$(
      timeout 20 git ls-remote --heads \
        https://github.com/aidycsolutions-ctrl/jugoo.git "refs/heads/${jugoo_ref}" \
        | awk 'NR==1 {print $1}'
    )" || true
    if [[ -n "${remote_sha}" && -n "${overlay_hash}" ]]; then
      jugoo_stamp="${remote_sha} ${overlay_hash}"
      if [[ -f "${jugoo_dir}/shell/__main__.py" && -f "${jugoo_stamp_file}" \
         && "$(cat "${jugoo_stamp_file}")" == "${jugoo_stamp}" ]]; then
        skip_jugoo_fetch=1
      fi
    fi
  fi

  if [[ "${skip_jugoo_fetch}" == 1 ]]; then
    jugoo_source="${jugoo_dir}"
  else
  staging_dir="$(mktemp -d "${TMPDIR:-/tmp}/aidycos-jugoo.XXXXXX")"
  trap 'rm -rf "${staging_dir}"' RETURN
  jugoo_source="${staging_dir}/jugoo"

  if [[ -n "${source_dir}" ]]; then
    if [[ ! -d "${source_dir}/.git" || ! -f "${source_dir}/shell/__main__.py" ]]; then
      echo "El checkout configurado de Jugoo no está disponible o no es válido: ${source_dir}" >&2
      echo "AidyCOS conserva ~/.config/jugoo y no la usará como reemplazo." >&2
      return 1
    fi
    source_dir="$(cd "${source_dir}" && pwd -P)"
    echo "AidyCOS usará este checkout solo para esta ejecución: ${source_dir}"
    echo "Se copia a un staging temporal; el overlay no modifica el checkout seleccionado."
    cp -a "${source_dir}" "${jugoo_source}"
  else
    mkdir -p "${config_home}"
    if [[ -r "${config_home}/aidycos/jugoo-source" ]]; then
      echo "Se conserva ${config_home}/aidycos/jugoo-source, pero ya no selecciona el código de Jugoo en actualizaciones."
    fi
    if ! git clone --depth 1 --branch "${jugoo_ref}" \
      https://github.com/aidycsolutions-ctrl/jugoo.git "${jugoo_source}"; then
      echo "No se pudo clonar la rama ${jugoo_ref}; se usa main." >&2
      rm -rf "${jugoo_source}"
      git clone --depth 1 https://github.com/aidycsolutions-ctrl/jugoo.git "${jugoo_source}"
    fi
  fi

  python3 "${ROOT}/packaging/jugoo-overlay/install.py" "${jugoo_source}"
  sudo install -d -m 0755 /opt/aidyc
  sudo python3 "${ROOT}/scripts/deploy-jugoo.py" "${jugoo_source}" "${jugoo_dir}"
  trap - RETURN
  rm -rf "${staging_dir}"
  fi

  sudo install -D -m 0755 "${ROOT}/packaging/jugoo-launcher" /usr/local/bin/jugoo
  # Parche de iconos AidyC/AidyChat en Jugoo sin tocar /opt si el overlay ya lo trajo.
  install -d "${HOME}/.local/share/aidycos/patches"
  install -m 0644 "${ROOT}/packaging/jugoo-overlay/shell/icons.py" \
    "${HOME}/.local/share/aidycos/patches/icons.py"
  # Session menu (Cancel/Esc + short Alt+F4 grace) loads via boot without rewriting /opt.
  if [[ -f "${ROOT}/packaging/jugoo-overlay/shell/popup_handle.py" ]]; then
    install -m 0644 "${ROOT}/packaging/jugoo-overlay/shell/popup_handle.py" \
      "${HOME}/.local/share/aidycos/patches/popup_handle.py"
  fi
  if [[ -f "${ROOT}/packaging/jugoo-overlay/shell/widgets/barra/power.py" ]]; then
    install -m 0644 "${ROOT}/packaging/jugoo-overlay/shell/widgets/barra/power.py" \
      "${HOME}/.local/share/aidycos/patches/power.py"
  fi
  if [[ -f "${ROOT}/packaging/jugoo-overlay/patches/jugoo_aidycos_boot.py" ]]; then
    install -m 0644 "${ROOT}/packaging/jugoo-overlay/patches/jugoo_aidycos_boot.py" \
      "${HOME}/.local/share/aidycos/patches/jugoo_aidycos_boot.py"
  fi
  if [[ -f "${ROOT}/packaging/jugoo-overlay/shell/runtime_relaunch.py" ]]; then
    install -m 0644 "${ROOT}/packaging/jugoo-overlay/shell/runtime_relaunch.py" \
      "${HOME}/.local/share/aidycos/patches/runtime_relaunch.py"
  fi
  install -D -m 0755 "${ROOT}/packaging/jugoo-launcher" "${HOME}/.local/bin/jugoo"
  install -D -m 0644 "${ROOT}/packaging/jugoo-overlay/aidyc.desktop" "${HOME}/.local/share/applications/aidyc.desktop"
  # Logo AidyC en hicolor + lanzador que marca WM_CLASS/icono sin recompilar AidyC.
  sudo install -d -m 0755 /usr/local/libexec/aidycos /usr/share/pixmaps
  if [[ -f "${ROOT}/packaging/aidyc/aidyc.png" ]]; then
    sudo install -D -m 0644 "${ROOT}/packaging/aidyc/aidyc.png" /usr/share/pixmaps/aidyc.png
  elif [[ -f /opt/aidyc/AidyC/Aidylogo.png ]]; then
    sudo install -D -m 0644 /opt/aidyc/AidyC/Aidylogo.png /usr/share/pixmaps/aidyc.png
  fi
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidyc/icons/aidyc-${icon_size}.png" ]]; then
      sudo install -D -m 0644 \
        "${ROOT}/packaging/aidyc/icons/aidyc-${icon_size}.png" \
        "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyc.png"
      install -D -m 0644 \
        "${ROOT}/packaging/aidyc/icons/aidyc-${icon_size}.png" \
        "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyc.png"
    fi
  done
  sudo install -m 0755 "${ROOT}/packaging/aidyc/aidyc-wrapper" /usr/local/bin/aidyc
  sudo install -m 0755 "${ROOT}/packaging/aidyc/aidyc-window-brand.py" /usr/local/libexec/aidycos/aidyc-window-brand.py
  refresh_icon_cache sudo /usr/share/icons/hicolor
  refresh_icon_cache user "${HOME}/.local/share/icons/hicolor"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
  fi
  # shell --install writes ~/.local/bin/jugoo as the current user. A root-owned
  # leftover there (from an earlier privileged copy) aborts with PermissionError.
  install -d "${HOME}/.local/bin"
  if [[ -e "${HOME}/.local/bin/jugoo" || -L "${HOME}/.local/bin/jugoo" ]]; then
    if [[ ! -O "${HOME}/.local/bin/jugoo" || ! -w "${HOME}/.local/bin/jugoo" ]]; then
      echo "Se elimina ${HOME}/.local/bin/jugoo (no escribible por el usuario) antes de reinstalar Jugoo."
      sudo rm -f "${HOME}/.local/bin/jugoo"
    fi
  fi
  if [[ "${skip_jugoo_fetch}" != 1 ]]; then
    # install -d does not loosen an existing /opt/aidyc (often 0700 from the
    # POS install). copytree also keeps a private clone mode, then root owns it.
    if [[ -d /opt/aidyc ]]; then
      sudo chmod a+rx /opt/aidyc
    fi
    if [[ -d "${jugoo_dir}" ]]; then
      sudo chmod -R a+rX "${jugoo_dir}"
    fi
    (cd "${jugoo_dir}" && python3 -m shell --install)
    if [[ -n "${jugoo_stamp}" ]]; then
      install -D -m 0644 /dev/null "${jugoo_stamp_file}"
      printf '%s\n' "${jugoo_stamp}" >"${jugoo_stamp_file}"
    fi
  fi
  # shell --install may create a user-local launcher and service. Keep the
  # launcher as a compatibility shim, and override the unit's command so both
  # entry points always execute the same system-managed checkout.
  if [[ -e "${HOME}/.local/bin/jugoo" || -L "${HOME}/.local/bin/jugoo" ]]; then
    if ! cmp -s "${ROOT}/packaging/jugoo-launcher" "${HOME}/.local/bin/jugoo"; then
      backup="${HOME}/.local/bin/jugoo.aidycos-backup"
      if [[ ! -e "${backup}" && ! -L "${backup}" ]]; then
        cp -a "${HOME}/.local/bin/jugoo" "${backup}"
      fi
      install -m 0755 "${ROOT}/packaging/jugoo-launcher" "${HOME}/.local/bin/jugoo"
    fi
  else
    install -m 0755 "${ROOT}/packaging/jugoo-launcher" "${HOME}/.local/bin/jugoo"
  fi
  # Never leave the user launcher owned by root.
  if [[ -e "${HOME}/.local/bin/jugoo" && ! -O "${HOME}/.local/bin/jugoo" ]]; then
    sudo chown "${USER}:${USER}" "${HOME}/.local/bin/jugoo" 2>/dev/null \
      || sudo chown "$(id -u):$(id -g)" "${HOME}/.local/bin/jugoo"
  fi
  local service_dir="${config_home}/systemd/user/jugoo-task-watcher.service.d"
  local service_dropin="${service_dir}/aidycos.conf"
  local service_src="${ROOT}/packaging/systemd/jugoo-task-watcher.service.d/aidycos.conf"
  if [[ ! -f "${service_dropin}" ]] || ! cmp -s "${service_src}" "${service_dropin}"; then
    install -D -m 0644 "${service_src}" "${service_dropin}"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user try-restart jugoo-task-watcher.service >/dev/null 2>&1 || true
  fi
  # hyprbars is owned by AidyCOS (packaging/hyprland/setup-hyprbars.sh) and runs
  # after the ventanas scripts are installed further below — Jugoo upstream does
  # not ship setup-hyprbars on the branches we clone.
}
install_jugoo

# Separate AidyC updater: the dock icon opens an installed copy, so updates
# need an explicit launcher that checks GitHub and compares Debian versions.
sudo install -m 0755 "${ROOT}/scripts/aidyc-update" /usr/local/bin/aidyc-update
sudo install -m 0755 "${ROOT}/scripts/aidycos-onlyoffice" /usr/local/bin/aidycos-onlyoffice
sudo install -m 0755 "${ROOT}/scripts/aidycos-cajon" /usr/local/bin/aidycos-cajon
install -D -m 0755 "${ROOT}/scripts/aidycos-cajon" "${HOME}/.local/bin/aidycos-cajon"
sudo install -m 0755 "${ROOT}/scripts/uninstall-debian-profile.sh" /usr/local/bin/aidycos-uninstall
install -D -m 0755 "${ROOT}/scripts/uninstall-debian-profile.sh" \
  "${HOME}/.local/bin/aidycos-uninstall"
install -D -m 0644 "${ROOT}/packaging/applications/aidyc-update.desktop" \
  "${HOME}/.local/share/applications/aidyc-update.desktop"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-uninstall.desktop" \
  "${HOME}/.local/share/applications/aidycos-uninstall.desktop"
# Friendly Spanish entry for the CUPS printer manager.
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-impresoras.desktop" \
  "${HOME}/.local/share/applications/aidycos-impresoras.desktop"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-cajon.desktop" \
  "${HOME}/.local/share/applications/aidycos-cajon.desktop"
# Synaptic + OnlyOffice helpers so users can install office and other apps.
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-paquetes.desktop" \
  "${HOME}/.local/share/applications/aidycos-paquetes.desktop"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-onlyoffice.desktop" \
  "${HOME}/.local/share/applications/aidycos-onlyoffice.desktop"
# Prefer the Flatpak OnlyOffice logo over the generic x-office-document icon.
install_onlyoffice_icons() {
  local src_root="" size src dest name
  for src_root in \
      "${HOME}/.local/share/flatpak/exports/share/icons/hicolor" \
      "/var/lib/flatpak/exports/share/icons/hicolor"; do
    if [[ -f "${src_root}/48x48/apps/org.onlyoffice.desktopeditors.png" ]]; then
      break
    fi
    src_root=""
  done
  [[ -n "${src_root}" ]] || return 0
  for size in 16 24 32 48 64 128 256; do
    src="${src_root}/${size}x${size}/apps/org.onlyoffice.desktopeditors.png"
    [[ -f "${src}" ]] || continue
    for name in org.onlyoffice.desktopeditors ONLYOFFICE aidycos-onlyoffice onlyoffice; do
      dest="${HOME}/.local/share/icons/hicolor/${size}x${size}/apps/${name}.png"
      install -D -m 0644 "${src}" "${dest}"
    done
  done
  refresh_icon_cache user "${HOME}/.local/share/icons/hicolor"
}
install_onlyoffice_icons
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi
# Ensure the GUI printer manager is present even on older installs.
if ! command -v system-config-printer >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends system-config-printer cups-client
fi
# Desktop user can add/share printers from Configuración → Impresoras (lpadmin).
if getent group lpadmin >/dev/null 2>&1; then
  if id -nG "${USER}" 2>/dev/null | tr ' ' '\n' | grep -qx lpadmin; then
    :
  else
    sudo usermod -aG lpadmin "${USER}"
    echo "Usuario ${USER} añadido al grupo lpadmin (cierra sesión para aplicarlo)."
  fi
fi
# Seed + apply the shared printer catalog so other AidyCOS PCs get queues
# without running lpadmin by hand.
printer_catalog_src="${ROOT}/packaging/printers/shared-printers.json"
printer_catalog_dst="${HOME}/.local/share/aidycos/shared-printers.json"
printer_stamp="${HOME}/.local/share/aidycos/printers-stamp"
if [[ -f "${printer_catalog_src}" ]]; then
  printer_hash="$(sha256sum "${printer_catalog_src}" | awk '{print $1}')"
  # force=True rewrites every queue and prints them as "actualizadas" even
  # when the catalog file did not change.
  if [[ -f "${printer_stamp}" && "$(cat "${printer_stamp}")" == "${printer_hash}" \
     && -f "${printer_catalog_dst}" ]]; then
    :
  else
    install -D -m 0644 "${printer_catalog_src}" "${printer_catalog_dst}"
    docs_dir="$(xdg-user-dir DOCUMENTS 2>/dev/null || true)"
    if [[ -n "${docs_dir}" && -d "${docs_dir}" ]]; then
      install -D -m 0644 "${printer_catalog_src}" "${docs_dir}/shared-printers.json"
    fi
    echo "Catálogo de impresoras AidyCOS listo en ${printer_catalog_dst}"
    if [[ -f "${ROOT}/scripts/apply-shared-printers.py" ]]; then
      if python3 "${ROOT}/scripts/apply-shared-printers.py" "${printer_catalog_dst}"; then
        printf '%s\n' "${printer_hash}" >"${printer_stamp}"
        echo "Impresoras compartidas aplicadas desde el catálogo AidyCOS."
      else
        echo "Aviso: no se pudieron aplicar las impresoras del catálogo (¿CUPS/lpadmin?)." >&2
      fi
    fi
  fi
fi
# Raw ESC/POS queue for the cash drawer. No-op when this PC has no ticket printer.
escpos_src="${ROOT}/packaging/printers/escpos.json"
escpos_dst="${HOME}/.local/share/aidycos/escpos.json"
if [[ -f "${escpos_src}" && ! -f "${escpos_dst}" ]]; then
  install -D -m 0644 "${escpos_src}" "${escpos_dst}"
fi
if [[ -f "${ROOT}/scripts/apply-escpos-printer.py" ]]; then
  if ! python3 "${ROOT}/scripts/apply-escpos-printer.py"; then
    echo "Aviso: no se pudo preparar la cola raw del cajón (Tickets)." >&2
  fi
fi
# Keep Synaptic/Flatpak available on older profiles that predate the module list.
if ! command -v synaptic >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends synaptic pkexec polkitd
fi
if ! command -v flatpak >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends flatpak
fi
# Firefox ESR is the default browser; older profiles only seeded the desktop icon.
if ! command -v firefox-esr >/dev/null 2>&1 && ! command -v firefox >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends firefox-esr
fi
if ! dpkg-query -W -f='${db:Status-Status}' adwaita-icon-theme 2>/dev/null | grep -qx installed; then
  sudo apt-get install -y --no-install-recommends adwaita-icon-theme hicolor-icon-theme
fi
# Adwaita 48 moved fullcolor app icons (system-software-update / -install) to
# AdwaitaLegacy; apt only Suggests that package, so install it explicitly.
if ! dpkg-query -W -f='${db:Status-Status}' adwaita-icon-theme-legacy 2>/dev/null | grep -qx installed; then
  sudo apt-get install -y --no-install-recommends adwaita-icon-theme-legacy
fi
# --no-install-recommends skips Adwaita's SVG loader; Jugoo then shows empty rectangles.
for pkg in librsvg2-common gvfs-fuse python3-gi-cairo; do
  if ! dpkg-query -W -f='${db:Status-Status}' "${pkg}" 2>/dev/null | grep -qx installed; then
    sudo apt-get install -y --no-install-recommends "${pkg}"
  fi
done
# Wallpaper UI (Configuración → Tema → Escritorio) needs swaybg on Wayland.
if ! command -v swaybg >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends swaybg
fi
if command -v flatpak >/dev/null 2>&1; then
  sudo flatpak remote-add --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo >/dev/null 2>&1 || true
  flatpak --user remote-add --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo >/dev/null 2>&1 || true
fi
# Seed wallpaper/icons after .desktop helpers exist (OnlyOffice, Synaptic, AidyChat).
python3 "${ROOT}/scripts/seed-desktop-defaults.py" || true
# GTK apps need an explicit icon theme on minimal Hyprland sessions.
# Also force minimize/maximize/close: GNOME/libadwaita CSD often hides minimize
# under the default decoration layout, and those apps skip hyprbars.
GTK3_SETTINGS="${XDG_CONFIG_HOME:-${HOME}/.config}/gtk-3.0/settings.ini"
GTK4_SETTINGS="${XDG_CONFIG_HOME:-${HOME}/.config}/gtk-4.0/settings.ini"
ensure_gtk_setting() {
  local gtk_settings="$1" key="$2" value="$3"
  mkdir -p "$(dirname "${gtk_settings}")"
  if [[ ! -f "${gtk_settings}" ]]; then
    printf '[Settings]\n%s=%s\n' "${key}" "${value}" >"${gtk_settings}"
    return
  fi
  if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "${gtk_settings}"; then
    sed -i -E "s|^[[:space:]]*${key}[[:space:]]*=.*|${key}=${value}|" "${gtk_settings}"
  elif grep -qE '^[[:space:]]*\[Settings\]' "${gtk_settings}"; then
    sed -i "/^[[:space:]]*\[Settings\]/a ${key}=${value}" "${gtk_settings}"
  else
    printf '\n[Settings]\n%s=%s\n' "${key}" "${value}" >>"${gtk_settings}"
  fi
}
for gtk_settings in "${GTK3_SETTINGS}" "${GTK4_SETTINGS}"; do
  ensure_gtk_setting "${gtk_settings}" "gtk-icon-theme-name" "Adwaita"
  ensure_gtk_setting "${gtk_settings}" "gtk-theme-name" "Adwaita"
  ensure_gtk_setting "${gtk_settings}" "gtk-decoration-layout" "icon:minimize,maximize,close"
done
refresh_icon_cache sudo /usr/share/icons/Adwaita
refresh_icon_cache sudo /usr/share/icons/hicolor

# Jugoo's network and battery indicators use NetworkManager and UPower.
# wpasupplicant (+ iw/rfkill/wireless firmware) comes from the aidyc-desktop
# module packages list; do not install a conflicting wpa_supplicant stack here.
# Migrate Debian-installer ifupdown Wi-Fi into NM so the bar does not show "LAN".
bash "${ROOT}/packaging/network/apply-aidycos-network.sh"
sudo systemctl enable --now upower.service

# Bluetooth panel in Jugoo uses BlueZ (bluetoothd). Keep the daemon enabled so
# the control-center toggle / device list works without a separate Blueman UI.
if ! dpkg-query -W -f='${db:Status-Status}' bluez 2>/dev/null | grep -qx installed; then
  sudo apt-get install -y --no-install-recommends bluez rfkill
fi
sudo systemctl enable --now bluetooth.service >/dev/null 2>&1 || true
if command -v rfkill >/dev/null 2>&1; then
  rfkill unblock bluetooth >/dev/null 2>&1 || true
fi
# Seat access for non-root bluetoothctl / BlueZ agent operations.
if getent group bluetooth >/dev/null 2>&1; then
  if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx bluetooth; then
    sudo usermod -aG bluetooth "${USER}" || true
    echo "Usuario ${USER} añadido al grupo bluetooth (hace falta cerrar sesión)."
  fi
fi

# Jugoo volume reads prefer pactl (pipewire-pulse). Without it, the bar can still
# change volume via wpctl but used to show a permanent mute "x". Keep the Pulse
# compatibility socket enabled for the graphical user session.
if dpkg-query -W -f='${db:Status-Status}' pipewire-pulse 2>/dev/null | grep -qx installed; then
  sudo systemctl enable --global pipewire-pulse.socket >/dev/null 2>&1 || true
  systemctl --user enable --now pipewire-pulse.socket pipewire-pulse.service >/dev/null 2>&1 || true
fi

# USB sticks need udisks2 + gvfs + Thunar daemon with automount enabled.
# A wireless mouse works without this stack (HID); removable storage does not.
sudo install -D -m 0644 \
  "${ROOT}/packaging/thunar/thunar-volman.xml" \
  /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar-volman.xml
mkdir -p "${XDG_CONFIG_HOME:-${HOME}/.config}/xfce4/xfconf/xfce-perchannel-xml"
install -m 0644 \
  "${ROOT}/packaging/thunar/thunar-volman.xml" \
  "${XDG_CONFIG_HOME:-${HOME}/.config}/xfce4/xfconf/xfce-perchannel-xml/thunar-volman.xml"
# Keep browser downloads on one folder (Descargas/Downloads) and poke Thunar
# when *.crdownload/*.part finalize so the final file shows up without F5.
sudo install -D -m 0755 \
  "${ROOT}/packaging/thunar/aidycos-download-dir.py" \
  /usr/local/bin/aidycos-download-dir
if ! command -v xdg-user-dirs-update >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends xdg-user-dirs
fi
/usr/local/bin/aidycos-download-dir ensure || true
if getent group plugdev >/dev/null 2>&1; then
  if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx plugdev; then
    sudo usermod -aG plugdev "${USER}" || true
    echo "Se añadió ${USER} al grupo plugdev (hace falta cerrar sesión para USB)."
  fi
fi
sudo systemctl enable --now udisks2.service >/dev/null 2>&1 || true

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
  # Un solo acceso en el menú: AidyChat. Quitar el .desktop viejo "AidyLink".
  sudo rm -f /usr/share/applications/aidylink.desktop
  # Logo AidyChat (PNG en tamaños hicolor; quitar SVG genérico anterior).
  sudo rm -f /usr/share/icons/hicolor/scalable/apps/aidychat.svg
  local icon_size
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidylink/icons/aidychat-${icon_size}.png" ]]; then
      sudo install -D -m 0644 \
        "${ROOT}/packaging/aidylink/icons/aidychat-${icon_size}.png" \
        "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidychat.png"
    fi
  done
  if [[ -f "${ROOT}/packaging/aidylink/aidychat.png" ]]; then
    sudo install -D -m 0644 "${ROOT}/packaging/aidylink/aidychat.png" /usr/share/pixmaps/aidychat.png
  fi
  install -d "${desktop_dir}" "${service_dir}"
  install -m 0644 "${desktop_entry}" "${desktop_dir}/aidychat.desktop"
  rm -f "${desktop_dir}/aidylink.desktop"
  mkdir -p "${HOME}/.local/share/icons/hicolor"
  rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/aidychat.svg"
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidylink/icons/aidychat-${icon_size}.png" ]]; then
      install -D -m 0644 \
        "${ROOT}/packaging/aidylink/icons/aidychat-${icon_size}.png" \
        "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidychat.png"
    fi
  done
  install -m 0644 "${ROOT}/packaging/aidylink/aidylink.service" "${service_dir}/aidylink.service"
  if command -v xdg-user-dir >/dev/null 2>&1; then
    user_desktop="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -z "${user_desktop}" || "${user_desktop}" == "${HOME}" ]]; then
    user_desktop="${HOME}/Desktop"
  fi
  mkdir -p "${user_desktop}"
  install -m 0755 "${desktop_entry}" "${user_desktop}/AidyChat.desktop"
  rm -f "${user_desktop}/AidyLink.desktop" "${user_desktop}/aidylink.desktop"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  refresh_icon_cache sudo /usr/share/icons/hicolor
  refresh_icon_cache user "${HOME}/.local/share/icons/hicolor"
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    update-desktop-database "${desktop_dir}" >/dev/null 2>&1 || true
  fi
  if [[ "${PROFILE_REFRESH}" != 1 ]]; then
    echo "AidyChat instalado. Abre el acceso del escritorio; la primera vez pide el nombre del PC y puedes emparejar otros con un código."
  fi
}
install_aidylink

install_aidyship() {
  local aidyship_dir=/opt/aidyc/aidyship
  local desktop_dir="${HOME}/.local/share/applications"
  local desktop_entry="${ROOT}/packaging/aidyship/aidyship.desktop"
  local icon_size
  # GitHub CLI is required for per-user login; git is already in the bootstrap set.
  if ! command -v gh >/dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends gh
  fi
  if ! dpkg-query -W -f='${db:Status-Status}' python3-gi 2>/dev/null | grep -qx 'installed'; then
    sudo apt-get install -y --no-install-recommends python3-gi gir1.2-gtk-3.0
  fi
  if ! command -v notify-send >/dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends libnotify-bin
  fi
  sudo install -d -m 0755 "${aidyship_dir}/aidyship" /usr/local/bin /usr/share/applications
  sudo install -m 0644 "${ROOT}/packaging/aidyship/aidyship/"*.py "${aidyship_dir}/aidyship/"
  sudo install -m 0644 "${ROOT}/packaging/aidyship/README.md" "${aidyship_dir}/README.md"
  if [[ -f "${ROOT}/packaging/aidyship/aidyship.png" ]]; then
    sudo install -D -m 0644 "${ROOT}/packaging/aidyship/aidyship.png" "${aidyship_dir}/aidyship.png"
    sudo install -D -m 0644 "${ROOT}/packaging/aidyship/aidyship.png" /usr/share/pixmaps/aidyship.png
  fi
  sudo install -m 0755 "${ROOT}/packaging/aidyship/aidyship-wrapper" /usr/local/bin/aidyship
  sudo install -m 0644 "${desktop_entry}" /usr/share/applications/aidyship.desktop
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidyship/icons/aidyship-${icon_size}.png" ]]; then
      sudo install -D -m 0644 \
        "${ROOT}/packaging/aidyship/icons/aidyship-${icon_size}.png" \
        "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyship.png"
    fi
  done
  install -d "${desktop_dir}" "${HOME}/.local/share/icons/hicolor"
  install -m 0644 "${desktop_entry}" "${desktop_dir}/aidyship.desktop"
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidyship/icons/aidyship-${icon_size}.png" ]]; then
      install -D -m 0644 \
        "${ROOT}/packaging/aidyship/icons/aidyship-${icon_size}.png" \
        "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyship.png"
    fi
  done
  refresh_icon_cache sudo /usr/share/icons/hicolor
  refresh_icon_cache user "${HOME}/.local/share/icons/hicolor"
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    update-desktop-database "${desktop_dir}" >/dev/null 2>&1 || true
  fi
  if [[ "${PROFILE_REFRESH}" != 1 ]]; then
    echo "AidyShip instalado. Abre el menú o Super+G; la primera vez pide conectar tu GitHub."
  fi
}
install_aidyship

install_aidyshare() {
  local aidyshare_dir=/opt/aidyc/aidyshare
  local desktop_dir="${HOME}/.local/share/applications"
  local desktop_entry="${ROOT}/packaging/aidyshare/aidyshare.desktop"
  local icon_size
  if ! dpkg-query -W -f='${db:Status-Status}' python3-gi 2>/dev/null | grep -qx 'installed'; then
    sudo apt-get install -y --no-install-recommends python3-gi gir1.2-gtk-3.0
  fi
  if ! command -v notify-send >/dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends libnotify-bin
  fi
  sudo install -d -m 0755 "${aidyshare_dir}/aidyshare" /usr/local/bin /usr/share/applications
  sudo install -m 0644 "${ROOT}/packaging/aidyshare/aidyshare/"*.py "${aidyshare_dir}/aidyshare/"
  sudo install -m 0644 "${ROOT}/packaging/aidyshare/README.md" "${aidyshare_dir}/README.md"
  if [[ -f "${ROOT}/packaging/aidyshare/aidyshare.png" ]]; then
    sudo install -D -m 0644 "${ROOT}/packaging/aidyshare/aidyshare.png" "${aidyshare_dir}/aidyshare.png"
    sudo install -D -m 0644 "${ROOT}/packaging/aidyshare/aidyshare.png" /usr/share/pixmaps/aidyshare.png
  fi
  sudo install -m 0755 "${ROOT}/packaging/aidyshare/aidyshare-wrapper" /usr/local/bin/aidyshare
  sudo install -m 0644 "${desktop_entry}" /usr/share/applications/aidyshare.desktop
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidyshare/icons/aidyshare-${icon_size}.png" ]]; then
      sudo install -D -m 0644 \
        "${ROOT}/packaging/aidyshare/icons/aidyshare-${icon_size}.png" \
        "/usr/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyshare.png"
    fi
  done
  install -d "${desktop_dir}" "${HOME}/.local/share/icons/hicolor"
  install -m 0644 "${desktop_entry}" "${desktop_dir}/aidyshare.desktop"
  for icon_size in 16 24 32 48 64 128 256 512; do
    if [[ -f "${ROOT}/packaging/aidyshare/icons/aidyshare-${icon_size}.png" ]]; then
      install -D -m 0644 \
        "${ROOT}/packaging/aidyshare/icons/aidyshare-${icon_size}.png" \
        "${HOME}/.local/share/icons/hicolor/${icon_size}x${icon_size}/apps/aidyshare.png"
    fi
  done
  refresh_icon_cache sudo /usr/share/icons/hicolor
  refresh_icon_cache user "${HOME}/.local/share/icons/hicolor"
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    update-desktop-database "${desktop_dir}" >/dev/null 2>&1 || true
  fi
  if [[ "${PROFILE_REFRESH}" != 1 ]]; then
    echo "AidyShare instalado. Login AidyC → respaldo en AidyCShare del negocio (500 MB)."
  fi
}
install_aidyshare

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
HYPR_DIR="${CONFIG_HOME}/hypr"
HYPR_CONF="${HYPR_DIR}/hyprland.conf"
HYPR_AIDYCOS_CONF="${HYPR_DIR}/aidycos.conf"
HYPR_WINDOWS_CONF="${HYPR_DIR}/config/jugoo_ventanas.conf"
HYPR_HYPERBARS_CONF="${HYPR_DIR}/config/jugoo_hyprbars.conf"
mkdir -p "${HYPR_DIR}" "${HYPR_DIR}/config" "${HYPR_DIR}/scripts"
CAPTURE_SCRIPT="${HOME}/.local/bin/captura.sh"
mkdir -p "$(dirname "${CAPTURE_SCRIPT}")"
if [[ ! -e "${CAPTURE_SCRIPT}" ]] || ! cmp -s "${ROOT}/packaging/hyprland/scripts/captura.sh" "${CAPTURE_SCRIPT}"; then
  if [[ -e "${CAPTURE_SCRIPT}" ]]; then
    cp -a "${CAPTURE_SCRIPT}" "${CAPTURE_SCRIPT}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  fi
  install -m 0755 "${ROOT}/packaging/hyprland/scripts/captura.sh" "${CAPTURE_SCRIPT}"
fi
install -m 0755 "${ROOT}/packaging/hyprland/scripts/ventanas" "${HYPR_DIR}/scripts/ventanas"
install -m 0644 "${ROOT}/packaging/hyprland/scripts/ventanas.py" "${HYPR_DIR}/scripts/ventanas.py"
install -m 0644 "${ROOT}/packaging/hyprland/scripts/decoraciones.py" "${HYPR_DIR}/scripts/decoraciones.py"
# Always refresh window-arrange binds so Ctrl+Alt+2/4/G keep working after updates.
if [[ -e "${HYPR_WINDOWS_CONF}" ]] && ! cmp -s "${ROOT}/packaging/hyprland/config/jugoo_ventanas.conf" "${HYPR_WINDOWS_CONF}"; then
  cp -a "${HYPR_WINDOWS_CONF}" "${HYPR_WINDOWS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
fi
install -m 0644 "${ROOT}/packaging/hyprland/config/jugoo_ventanas.conf" "${HYPR_WINDOWS_CONF}"
sudo install -m 0755 "${ROOT}/packaging/hyprland/aidycos-prefer-external-display" /usr/local/bin/aidycos-prefer-external-display
sudo install -m 0755 "${ROOT}/packaging/hyprland/aidycos-numlock" /usr/local/bin/aidycos-numlock

# Title-bar buttons: compile hyprbars here (not via Jugoo). Sources are vendored
# so flaky GitHub/SSL on test laptops cannot leave windows without min/close.
# hyprland-dev still comes from backports; failure must abort the profile.
# HYPRBARS_FORCE=1 rebuilds even when the version stamp matches (repair path).
if ! bash "${ROOT}/packaging/hyprland/setup-hyprbars.sh"; then
  echo "ERROR: no se pudieron instalar los botones de título (hyprbars)." >&2
  echo "Sin ~/.local/lib/jugoo/hyprbars.so las ventanas no muestran minimizar/cerrar." >&2
  echo "Revisa hyprland-dev (trixie-backports) y libhyprutils-dev (debe coincidir con version.h)." >&2
  echo "Reparación manual: HYPRBARS_FORCE=1 bash packaging/hyprland/setup-hyprbars.sh" >&2
  exit 1
fi
if [[ ! -f "${HOME}/.local/lib/jugoo/hyprbars.so" || ! -f "${HYPR_HYPERBARS_CONF}" ]]; then
  echo "ERROR: hyprbars no quedó instalado tras setup-hyprbars.sh." >&2
  exit 1
fi
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
  if ! hyprctl plugin list 2>/dev/null | grep -qi '^Plugin hyprbars'; then
    echo "ERROR: hyprbars.so existe pero Hyprland no cargó el plugin." >&2
    echo "Prueba: HYPRBARS_FORCE=1 bash ${ROOT}/packaging/hyprland/setup-hyprbars.sh && hyprctl reload" >&2
    hyprctl plugin list 2>/dev/null || true
    exit 1
  fi
fi
# CSD minimize: Cursor/Chrome/Electron draw their own caption buttons; Hyprland
# ignores those minimize clicks unless csd-minimize routes them to ventanas.
if ! bash "${ROOT}/packaging/hyprland/setup-csd-minimize.sh"; then
  echo "ERROR: no se pudo instalar csd-minimize (minimizar de Cursor/Chrome)." >&2
  echo "Reparación: CSD_MINIMIZE_FORCE=1 bash packaging/hyprland/setup-csd-minimize.sh" >&2
  exit 1
fi
if [[ ! -f "${HOME}/.local/lib/jugoo/csd-minimize.so" || ! -f "${HYPR_DIR}/config/jugoo_csd_minimize.conf" ]]; then
  echo "ERROR: csd-minimize no quedó instalado tras setup-csd-minimize.sh." >&2
  exit 1
fi
if [[ ! -e "${HYPR_AIDYCOS_CONF}" ]]; then
  cat >"${HYPR_AIDYCOS_CONF}" <<'EOF'
# AidyCOS keyboard and Jugoo defaults.
env = XDG_CURRENT_DESKTOP,Hyprland
env = XDG_SESSION_TYPE,wayland
misc {
    focus_on_activate = true
}
input {
    numlock_by_default = true
    kb_file = ~/.config/hypr/aidycos-keymap.xkb
}
bind = SUPER, SPACE, exec, jugoo action launcher
bind = SUPER, E, exec, /usr/bin/env GDK_BACKEND=wayland /usr/bin/thunar
bind = SUPER, G, exec, aidyship ui
bind = , Print, exec, ~/.local/bin/captura.sh
bind = ALT, F4, exec, jugoo action session
bind = , F6, exec, /usr/local/bin/aidycos-cajon
# Super+Left/Right snap is owned by jugoo_ventanas.conf (Windows-like).
bind = SUPER, Y, workspace, +1
bind = SUPER SHIFT, U, exec, aidycos-update --check
exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DISPLAY
exec-once = /usr/local/bin/aidycos-prefer-external-display
exec-once = /usr/local/bin/aidycos-numlock
exec-once = /usr/local/bin/aidycos-cajon watch
exec-once = /usr/bin/thunar --daemon
exec-once = /usr/local/bin/aidycos-download-dir ensure
exec-once = /usr/local/bin/aidycos-download-dir watch
EOF
  printf 'exec-once = %s\n' "${POLKIT_AGENT}" >>"${HYPR_AIDYCOS_CONF}"
else
  missing=0
  grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}" || missing=1
  if ! grep -qE '^[[:space:]]*focus_on_activate[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*focus_on_activate[[:space:]]*=[[:space:]]*true' "${HYPR_CONF}"; }; then
    if grep -qE '^[[:space:]]*misc[[:space:]]*\{' "${HYPR_AIDYCOS_CONF}"; then
      sed -i '/^[[:space:]]*misc[[:space:]]*{/a\    focus_on_activate = true' "${HYPR_AIDYCOS_CONF}"
    else
      printf '\nmisc {\n    focus_on_activate = true\n}\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
  fi
  grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}" || missing=1
  # Drop legacy Ctrl+Space launcher (canonical is Super+Space).
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}"; then
    missing=1
  fi
  if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*E,' "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*E,' "${HYPR_CONF}"; }; then
    missing=1
  fi
  # Migrate legacy Ctrl+E → Super+E for Thunar.
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*E,' "${HYPR_AIDYCOS_CONF}"; then
    missing=1
  fi
  if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*,[[:space:]]*Print,' "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*,[[:space:]]*Print,' "${HYPR_CONF}"; }; then
    missing=1
  fi
  if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT,[[:space:]]*F4,[[:space:]]*exec,[[:space:]]*jugoo action session' "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT,[[:space:]]*F4,[[:space:]]*exec,[[:space:]]*jugoo action session' "${HYPR_CONF}"; }; then
    missing=1
  fi
  # Legacy: Super+Left/Right used to switch desktops; now they snap (ventanas).
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,' "${HYPR_AIDYCOS_CONF}" 2>/dev/null \
     || grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,' "${HYPR_CONF}" 2>/dev/null; then
    missing=1
  fi
  grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_AIDYCOS_CONF}" || grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_CONF}" 2>/dev/null || missing=1
  # Super+C is reserved for Cursor (hyprland.conf); strip any old AidyChat bind.
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui' "${HYPR_AIDYCOS_CONF}"; then
    missing=1
  fi
  grep -qF 'exec-once = /usr/local/bin/aidycos-prefer-external-display' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'exec-once = /usr/local/bin/aidycos-numlock' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*(hyprpolkitagent|polkit-mate-authentication-agent-1)' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'bind = SUPER SHIFT, U, exec, aidycos-update --check' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'bind = SUPER, G, exec, aidyship ui' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*dbus-update-activation-environment' "${HYPR_AIDYCOS_CONF}" \
    || grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*dbus-update-activation-environment' "${HYPR_CONF}" 2>/dev/null \
    || missing=1
  grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*thunar[[:space:]]+--daemon' "${HYPR_AIDYCOS_CONF}" \
    || grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*thunar[[:space:]]+--daemon' "${HYPR_CONF}" 2>/dev/null \
    || missing=1
  grep -qF 'exec-once = /usr/local/bin/aidycos-download-dir ensure' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qF 'exec-once = /usr/local/bin/aidycos-download-dir watch' "${HYPR_AIDYCOS_CONF}" || missing=1
  grep -qE '^[[:space:]]*env[[:space:]]*=[[:space:]]*XDG_CURRENT_DESKTOP,' "${HYPR_AIDYCOS_CONF}" \
    || grep -qE '^[[:space:]]*env[[:space:]]*=[[:space:]]*XDG_CURRENT_DESKTOP,' "${HYPR_CONF}" 2>/dev/null \
    || missing=1
  if [[ "${missing}" == 1 ]]; then
    cp -a "${HYPR_AIDYCOS_CONF}" "${HYPR_AIDYCOS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    if ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}"; then
      cat >>"${HYPR_AIDYCOS_CONF}" <<'EOF'

input {
    numlock_by_default = true
    kb_file = ~/.config/hypr/aidycos-keymap.xkb
}
EOF
    fi
    # Canonical path is /usr/local/bin; drop temporary ~/.local/bin copies.
    if ! grep -qF 'exec-once = /usr/local/bin/aidycos-numlock' "${HYPR_AIDYCOS_CONF}"; then
      sed -i -E '\|^[[:space:]]*exec-once[[:space:]]*=.*aidycos-numlock|d' "${HYPR_AIDYCOS_CONF}"
      printf 'exec-once = /usr/local/bin/aidycos-numlock\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}"; then
      printf '\nbind = SUPER, SPACE, exec, jugoo action launcher\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher' "${HYPR_AIDYCOS_CONF}"; then
      sed -i -E '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*SPACE,[[:space:]]*exec,[[:space:]]*jugoo action launcher/d' "${HYPR_AIDYCOS_CONF}"
    fi
    if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*E,' "${HYPR_AIDYCOS_CONF}"; then
      sed -i -E 's/^[[:space:]]*bind[[:space:]]*=[[:space:]]*CTRL,[[:space:]]*E,/bind = SUPER, E,/' "${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*E,' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*E,' "${HYPR_CONF}"; }; then
      printf 'bind = SUPER, E, exec, /usr/bin/env GDK_BACKEND=wayland /usr/bin/thunar\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*,[[:space:]]*Print,' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*,[[:space:]]*Print,' "${HYPR_CONF}"; }; then
      printf 'bind = , Print, exec, ~/.local/bin/captura.sh\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT,[[:space:]]*F4,[[:space:]]*exec,[[:space:]]*jugoo action session' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT,[[:space:]]*F4,[[:space:]]*exec,[[:space:]]*jugoo action session' "${HYPR_CONF}"; }; then
      printf 'bind = ALT, F4, exec, jugoo action session\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    # Drop Super+Left/Right workspace binds so jugoo_ventanas.conf can snap.
    for hypr_file in "${HYPR_AIDYCOS_CONF}" "${HYPR_CONF}"; do
      if [[ -f "${hypr_file}" ]] && grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,' "${hypr_file}"; then
        sed -i -E '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,/d' "${hypr_file}"
        echo "Super+Left/Right ya no cambian de escritorio en ${hypr_file} (ahora dividen ventana)."
      fi
    done
    if ! grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_CONF}"; }; then
      printf 'bind = SUPER, Y, workspace, +1\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui' "${HYPR_AIDYCOS_CONF}"; then
      sed -i -E '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui/d' "${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'exec-once = /usr/local/bin/aidycos-prefer-external-display' "${HYPR_AIDYCOS_CONF}"; then
      printf 'exec-once = /usr/local/bin/aidycos-prefer-external-display\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*(hyprpolkitagent|polkit-mate-authentication-agent-1)' "${HYPR_AIDYCOS_CONF}"; then
      printf 'exec-once = %s\n' "${POLKIT_AGENT}" >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'bind = SUPER SHIFT, U, exec, aidycos-update --check' "${HYPR_AIDYCOS_CONF}"; then
      printf 'bind = SUPER SHIFT, U, exec, aidycos-update --check\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'bind = SUPER, G, exec, aidyship ui' "${HYPR_AIDYCOS_CONF}"; then
      printf 'bind = SUPER, G, exec, aidyship ui\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*env[[:space:]]*=[[:space:]]*XDG_CURRENT_DESKTOP,' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*env[[:space:]]*=[[:space:]]*XDG_CURRENT_DESKTOP,' "${HYPR_CONF}"; }; then
      printf 'env = XDG_CURRENT_DESKTOP,Hyprland\nenv = XDG_SESSION_TYPE,wayland\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*dbus-update-activation-environment' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*dbus-update-activation-environment' "${HYPR_CONF}"; }; then
      printf 'exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DISPLAY\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*thunar[[:space:]]+--daemon' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*thunar[[:space:]]+--daemon' "${HYPR_CONF}"; }; then
      printf 'exec-once = /usr/bin/thunar --daemon\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'exec-once = /usr/local/bin/aidycos-download-dir ensure' "${HYPR_AIDYCOS_CONF}"; then
      printf 'exec-once = /usr/local/bin/aidycos-download-dir ensure\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'exec-once = /usr/local/bin/aidycos-download-dir watch' "${HYPR_AIDYCOS_CONF}"; then
      printf 'exec-once = /usr/local/bin/aidycos-download-dir watch\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
  fi
fi

# Load arrange binds once: prefer hyprland.conf, else aidycos.conf (never both).
if grep -qF 'source = ~/.config/hypr/config/jugoo_ventanas.conf' "${HYPR_CONF}" 2>/dev/null; then
  if [[ -f "${HYPR_AIDYCOS_CONF}" ]] && grep -qF 'source = ~/.config/hypr/config/jugoo_ventanas.conf' "${HYPR_AIDYCOS_CONF}"; then
    sed -i '\|^[[:space:]]*source[[:space:]]*=[[:space:]]*~/.config/hypr/config/jugoo_ventanas.conf[[:space:]]*$|d' "${HYPR_AIDYCOS_CONF}"
  fi
elif [[ -f "${HYPR_AIDYCOS_CONF}" ]] && ! grep -qF 'source = ~/.config/hypr/config/jugoo_ventanas.conf' "${HYPR_AIDYCOS_CONF}"; then
  printf 'source = ~/.config/hypr/config/jugoo_ventanas.conf\n' >>"${HYPR_AIDYCOS_CONF}"
elif [[ ! -f "${HYPR_AIDYCOS_CONF}" ]]; then
  printf '\nsource = ~/.config/hypr/config/jugoo_ventanas.conf\n' >>"${HYPR_CONF}"
fi

# Alt+Tab must be owned only by jugoo_ventanas.conf. Skel hyprland.conf still ships
# cyclenext+bringactivetotop; when both fire with 2 windows the cycle takes two
# steps and looks like focus was lost without switching.
for hypr_file in "${HYPR_CONF}" "${HYPR_AIDYCOS_CONF}"; do
  if [[ -f "${hypr_file}" ]] && grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT([[:space:]]+SHIFT)?,[[:space:]]*Tab,' "${hypr_file}"; then
    cp -a "${hypr_file}" "${hypr_file}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E \
      -e '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT([[:space:]]+SHIFT)?,[[:space:]]*Tab,[[:space:]]*cyclenext/d' \
      -e '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT([[:space:]]+SHIFT)?,[[:space:]]*Tab,[[:space:]]*bringactivetotop/d' \
      -e '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*ALT([[:space:]]+SHIFT)?,[[:space:]]*Tab,[[:space:]]*exec,[[:space:]]*.*ventanas/d' \
      "${hypr_file}"
    if grep -qF 'cross-desktop cycle via ventanas' "${hypr_file}"; then
      sed -i 's/cross-desktop cycle via ventanas/current-desktop cycle via ventanas/g' "${hypr_file}"
    fi
    if ! grep -qF 'Alt+Tab is owned by jugoo_ventanas.conf' "${hypr_file}"; then
      printf '\n# Alt+Tab is owned by jugoo_ventanas.conf (current-desktop cycle via ventanas).\n' >>"${hypr_file}"
    fi
    echo "Alt+Tab duplicado eliminado de ${hypr_file} (queda solo jugoo_ventanas.conf)."
  fi
done

# Super+Up/Down and Super+Ctrl+Left/Right are owned by jugoo_ventanas.conf
# (maximize / change desktop). Duplicate movefocus/movetoworkspace binds make
# the front window look "stuck" because two actions fire on one keypress.
for hypr_file in "${HYPR_CONF}" "${HYPR_AIDYCOS_CONF}"; do
  [[ -f "${hypr_file}" ]] || continue
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(Up|Down),[[:space:]]*movefocus,' "${hypr_file}" \
    || grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER[[:space:]]+CTRL,[[:space:]]*(Left|Right),[[:space:]]*movetoworkspace,' "${hypr_file}"; then
    cp -a "${hypr_file}" "${hypr_file}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E \
      -e '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(Up|Down),[[:space:]]*movefocus,/d' \
      -e '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER[[:space:]]+CTRL,[[:space:]]*(Left|Right),[[:space:]]*movetoworkspace,/d' \
      "${hypr_file}"
    echo "Binds Super+flechas/Ctrl duplicados eliminados de ${hypr_file} (queda jugoo_ventanas.conf)."
  fi
done

# Super+Left/Right must snap (jugoo_ventanas.conf), not switch desktops. Strip the
# old workspace binds from any Hyprland file so they cannot fight the snap binds.
for hypr_file in "${HYPR_CONF}" "${HYPR_AIDYCOS_CONF}"; do
  if [[ -f "${hypr_file}" ]] && grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,' "${hypr_file}"; then
    cp -a "${hypr_file}" "${hypr_file}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E '/^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*(LEFT|RIGHT),[[:space:]]*workspace,/d' "${hypr_file}"
    echo "Super+Left/Right de escritorio eliminado de ${hypr_file} (ahora dividen como Windows)."
  fi
done

# Super+Space launcher must fire once. hyprland.conf (Space) + aidycos.conf (SPACE)
# both register → toggle opens then closes instantly (looks broken).
_launcher_bind_re='^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*[Ss][Pp][Aa][Cc][Ee],[[:space:]]*exec,[[:space:]]*jugoo action launcher'
if [[ -f "${HYPR_AIDYCOS_CONF}" ]] && grep -qE "${_launcher_bind_re}" "${HYPR_AIDYCOS_CONF}"; then
  if [[ -f "${HYPR_CONF}" ]] && grep -qE "${_launcher_bind_re}" "${HYPR_CONF}"; then
    cp -a "${HYPR_CONF}" "${HYPR_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E "/${_launcher_bind_re}/d" "${HYPR_CONF}"
    echo "Super+Space launcher duplicado eliminado de ${HYPR_CONF} (queda solo aidycos.conf)."
  fi
elif [[ -f "${HYPR_CONF}" ]] && grep -qE "${_launcher_bind_re}" "${HYPR_CONF}"; then
  # Migrate the only copy into aidycos.conf so future updates own one place.
  if [[ ! -f "${HYPR_AIDYCOS_CONF}" ]]; then
    printf '# AidyCOS keyboard and Jugoo defaults.\n' >"${HYPR_AIDYCOS_CONF}"
  fi
  cp -a "${HYPR_CONF}" "${HYPR_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  printf '\nbind = SUPER, SPACE, exec, jugoo action launcher\n' >>"${HYPR_AIDYCOS_CONF}"
  sed -i -E "/${_launcher_bind_re}/d" "${HYPR_CONF}"
  echo "Super+Space launcher movido de hyprland.conf a aidycos.conf."
fi
# GNOME/IBus default Super+Space for input-source switch; free it for the launcher.
if command -v gsettings >/dev/null 2>&1; then
  gsettings set org.gnome.desktop.wm.keybindings switch-input-source "['XF86Keyboard']" >/dev/null 2>&1 || true
  gsettings set org.gnome.desktop.wm.keybindings switch-input-source-backward "['<Shift>XF86Keyboard']" >/dev/null 2>&1 || true
  gsettings set org.freedesktop.ibus.general.hotkey triggers "[]" >/dev/null 2>&1 || true
fi
unset _launcher_bind_re

# Hot-apply window manager bits so a normal aidycos-update does not need a
# manual hyprctl reload / daemon restart (or logout) for Alt+Tab and snaps.
reload_hypr_windows() {
  local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  local pidfile="${runtime}/jugoo-ventanas.pid"
  local old_pid=""
  [[ -r "${pidfile}" ]] && old_pid="$(tr -d '[:space:]' <"${pidfile}" || true)"
  if [[ -n "${old_pid}" ]]; then
    kill "${old_pid}" 2>/dev/null || true
  fi
  # Clear stale FIFO/pid even if the old process already exited.
  rm -f "${runtime}/jugoo-ventanas.fifo" "${pidfile}"
  if command -v hyprctl >/dev/null 2>&1 && [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}${WAYLAND_DISPLAY:-}" ]]; then
    hyprctl reload >/dev/null 2>&1 || true
  fi
  # exec-once does not re-run on reload; start the daemon if Hyprland is up.
  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    if ! kill -0 "$(tr -d '[:space:]' <"${pidfile}" 2>/dev/null || true)" 2>/dev/null; then
      nohup python3 "${HYPR_DIR}/scripts/ventanas.py" daemon >/dev/null 2>&1 &
      disown || true
    fi
    echo "Hyprland recargado y daemon de ventanas reiniciado (Alt+Tab listo sin cerrar sesión)."
  fi
}
reload_hypr_windows

# Hyprland's first-run config ships `autogenerated = 1`, which keeps the yellow
# "You're using an autogenerated config!" banner even after AidyCOS appends
# source/jugoo lines. Always clear that marker when we manage the file.
clear_hyprland_autogenerated() {
  local conf=$1
  local already_backed_up=${2:-0}
  local touched=0
  [[ -f "${conf}" ]] || return 0
  if grep -qE '^[[:space:]]*autogenerated[[:space:]]*=[[:space:]]*1([[:space:]]|$)' "${conf}"; then
    if [[ "${already_backed_up}" != 1 ]]; then
      cp -a "${conf}" "${conf}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    fi
    # Comment out rather than delete so the user can see why it changed.
    sed -i -E 's/^[[:space:]]*autogenerated[[:space:]]*=[[:space:]]*1([[:space:]].*)?$/# autogenerated = 0  # AidyCOS: quita el aviso de config autogenerada/' "${conf}"
    echo "Aviso de config autogenerada desactivado en ${conf}"
    touched=1
  fi
  # Stock first-run also shows the Hyprland logo wallpaper; silence it when missing.
  if ! grep -qE '^[[:space:]]*disable_hyprland_logo[[:space:]]*=[[:space:]]*true' "${conf}"; then
    if [[ "${already_backed_up}" != 1 && "${touched}" != 1 ]]; then
      cp -a "${conf}" "${conf}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    fi
    if grep -qE '^[[:space:]]*misc[[:space:]]*\{' "${conf}"; then
      python3 - "${conf}" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
if re.search(r"(?m)^\s*disable_hyprland_logo\s*=\s*true\s*$", text):
    raise SystemExit(0)
match = re.search(r"(?m)^(?P<indent>\s*)misc\s*\{", text)
if not match:
    raise SystemExit(0)
indent = match.group("indent")
insert_at = match.end()
insertion = (
        f"\n{indent}    disable_hyprland_logo = true"
        f"\n{indent}    force_default_wallpaper = 0"
        f"\n{indent}    focus_on_activate = true"
    )
path.write_text(text[:insert_at] + insertion + text[insert_at:])
PY
    else
      cat >>"${conf}" <<'EOF'

misc {
    disable_hyprland_logo = true
    force_default_wallpaper = 0
    focus_on_activate = true
}
EOF
    fi
  fi
}

if [[ ! -e "${HYPR_CONF}" ]]; then
  cat >"${HYPR_CONF}" <<'EOF'
# AidyCOS: configuración base compatible con el perfil inicial.
# autogenerated = 0
source = ~/.config/hypr/aidycos.conf
monitor = , preferred, auto, 1
env = XDG_CURRENT_DESKTOP,Hyprland
env = XDG_SESSION_TYPE,wayland
input {
    kb_layout = latam
    numlock_by_default = true
    kb_file = ~/.config/hypr/aidycos-keymap.xkb
}
general {
    border_size = 2
    gaps_in = 4
    gaps_out = 8
}
decoration {
    rounding = 8
}
misc {
    disable_hyprland_logo = true
    force_default_wallpaper = 0
    focus_on_activate = true
}
exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DISPLAY
exec-once = /usr/local/bin/jugoo
bind = SUPER, Q, killactive
bind = SUPER, RETURN, exec, foot
bind = SUPER, M, exit
EOF
  echo "Configuración base creada en ${HYPR_CONF}"
else
  changed=0
  if grep -qE '^[[:space:]]*autogenerated[[:space:]]*=[[:space:]]*1([[:space:]]|$)' "${HYPR_CONF}"; then
    changed=1
  fi
  if ! grep -qE '^[[:space:]]*source[[:space:]]*=.*aidycos\.conf' "${HYPR_CONF}"; then
    changed=1
  fi
  if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*jugoo' "${HYPR_CONF}"; then
    changed=1
  fi
  if ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_CONF}"; then
    changed=1
  fi
  if [[ "${changed}" == 1 ]]; then
    backup="${HYPR_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    cp -a "${HYPR_CONF}" "${backup}"
    clear_hyprland_autogenerated "${HYPR_CONF}" 1
    if ! grep -qE '^[[:space:]]*source[[:space:]]*=.*aidycos\.conf' "${HYPR_CONF}"; then
      printf '\n# AidyCOS keyboard defaults.\nsource = ~/.config/hypr/aidycos.conf\n' >>"${HYPR_CONF}"
    fi
    if ! grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*jugoo' "${HYPR_CONF}"; then
      cat >>"${HYPR_CONF}" <<'EOF'

# AidyCOS: iniciar Jugoo al entrar en Hyprland.
exec-once = /usr/local/bin/jugoo
EOF
    fi
    # Si hyprland.conf tiene input{} propio y no carga aidycos.conf a tiempo,
    # NumLock queda apagado tras el login. Inyectar en el bloque input principal.
    if ! grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_CONF}"; then
      if grep -qE '^[[:space:]]*input[[:space:]]*\{' "${HYPR_CONF}"; then
        python3 - "${HYPR_CONF}" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
if re.search(r"(?m)^\s*numlock_by_default\s*=\s*true\s*$", text):
    raise SystemExit(0)
pattern = re.compile(r"(?m)^(?P<indent>\s*)input\s*\{")
match = pattern.search(text)
if not match:
    raise SystemExit(0)
indent = match.group("indent")
insert_at = match.end()
insertion = f"\n{indent}    numlock_by_default = true"
path.write_text(text[:insert_at] + insertion + text[insert_at:])
PY
      else
        cat >>"${HYPR_CONF}" <<'EOF'

input {
    numlock_by_default = true
    kb_file = ~/.config/hypr/aidycos-keymap.xkb
}
EOF
      fi
    fi
    echo "Se agregaron los ajustes AidyCOS; respaldo previo: ${backup}"
  else
    # Even when other markers already match, still clear a leftover banner flag.
    clear_hyprland_autogenerated "${HYPR_CONF}"
  fi
fi

# KP_Enter (Intro del numérico) se entrega como Return. Reescribe el keymap
# con el kb_layout que ya tenga el usuario y apunta input.kb_file a él.
if [[ -f "${ROOT}/scripts/apply-hypr-keymap.py" ]]; then
  if ! python3 "${ROOT}/scripts/apply-hypr-keymap.py" "${HYPR_DIR}"; then
    echo "Aviso: no se pudo mapear KP_Enter a Enter." >&2
  fi
fi
# F6 abre el cajón. El vigilante lo abre al terminar una factura en XPRINTER.
if [[ -f "${ROOT}/scripts/aidycos-cajon" && -n "${HYPR_AIDYCOS_CONF:-}" ]]; then
  if ! python3 "${ROOT}/scripts/aidycos-cajon" install-session "${HYPR_AIDYCOS_CONF}"; then
    echo "Aviso: no se pudo dejar F6 ni el vigilante del cajón." >&2
  fi
fi

# Upgrade older profiles that launched the generated ~/.local/bin copy. The
# compatibility shim uses the same system entry point as the user service.
if grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*(~/.local/bin/jugoo|/usr/local/bin/jugoo|(^|[[:space:]])jugoo([[:space:]]|$))' "${HYPR_CONF}"; then
  if grep -qE '^[[:space:]]*exec-once[[:space:]]*=.*~/.local/bin/jugoo' "${HYPR_CONF}"; then
    cp -a "${HYPR_CONF}" "${HYPR_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    sed -i -E 's|exec-once([[:space:]]*=[[:space:]]*)~/.local/bin/jugoo|exec-once\1/usr/local/bin/jugoo|' "${HYPR_CONF}"
  fi
fi

# Only load the optional hyprbars plugin config after the setup script has
# actually created it. Remove stale managed references left by failed installs.
HYPR_HYPERBARS_SOURCE='source = ~/.config/hypr/config/jugoo_hyprbars.conf'
if [[ -f "${HYPR_HYPERBARS_CONF}" ]]; then
  if ! grep -qF "${HYPR_HYPERBARS_SOURCE}" "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qF "${HYPR_HYPERBARS_SOURCE}" "${HYPR_CONF}"; }; then
    cp -a "${HYPR_AIDYCOS_CONF}" "${HYPR_AIDYCOS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    printf '\n%s\n' "${HYPR_HYPERBARS_SOURCE}" >>"${HYPR_AIDYCOS_CONF}"
  fi
else
  for config in "${HYPR_AIDYCOS_CONF}" "${HYPR_CONF}"; do
    if [[ -f "${config}" ]] && grep -qF "${HYPR_HYPERBARS_SOURCE}" "${config}"; then
      cp -a "${config}" "${config}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
      sed -i '\|^[[:space:]]*source[[:space:]]*=[[:space:]]*~/.config/hypr/config/jugoo_hyprbars.conf[[:space:]]*$|d' "${config}"
    fi
  done
fi

HYPR_CSD_MINIMIZE_CONF="${HYPR_DIR}/config/jugoo_csd_minimize.conf"
HYPR_CSD_MINIMIZE_SOURCE='source = ~/.config/hypr/config/jugoo_csd_minimize.conf'
if [[ -f "${HYPR_CSD_MINIMIZE_CONF}" ]]; then
  if ! grep -qF "${HYPR_CSD_MINIMIZE_SOURCE}" "${HYPR_AIDYCOS_CONF}" \
     && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qF "${HYPR_CSD_MINIMIZE_SOURCE}" "${HYPR_CONF}"; }; then
    cp -a "${HYPR_AIDYCOS_CONF}" "${HYPR_AIDYCOS_CONF}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    printf '\n%s\n' "${HYPR_CSD_MINIMIZE_SOURCE}" >>"${HYPR_AIDYCOS_CONF}"
  fi
else
  for config in "${HYPR_AIDYCOS_CONF}" "${HYPR_CONF}"; do
    if [[ -f "${config}" ]] && grep -qF "${HYPR_CSD_MINIMIZE_SOURCE}" "${config}"; then
      cp -a "${config}" "${config}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
      sed -i '\|^[[:space:]]*source[[:space:]]*=[[:space:]]*~/.config/hypr/config/jugoo_csd_minimize.conf[[:space:]]*$|d' "${config}"
    fi
  done
fi

# Quiet boot splash: GRUB logo + Plymouth. Absolute /usr/sbin paths matter on
# Debian user PATH (update-grub is not in /usr/bin).
bash "${ROOT}/packaging/boot/apply-aidycos-boot.sh"

if command -v systemctl >/dev/null && systemctl list-unit-files cups-browsed.service >/dev/null 2>&1; then
  override=/etc/systemd/system/cups-browsed.service.d/aidycos.conf
  cups_changed=0
  if [[ ! -e "${override}" ]]; then
    sudo install -d /etc/systemd/system/cups-browsed.service.d
    printf '[Unit]\nAfter=graphical.target\n' | sudo tee "${override}" >/dev/null
    cups_changed=1
  elif ! sudo grep -q '^After=graphical.target$' "${override}"; then
    echo "Se conserva el override existente de cups-browsed: ${override}"
  fi
  if [[ "${cups_changed}" == 1 ]]; then
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
     || ! sudo grep -q '^InputMethod=$' "${sddm_conf}" \
     || sudo grep -q '^GreeterEnvironment=' "${sddm_conf}"; then
    sddm_needs_update=1
  fi
  if [[ -e "${sddm_conf}" && "${sddm_needs_update}" == 1 ]]; then
    sudo cp -a "${sddm_conf}" "${sddm_conf}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
    echo "Se respaldó la configuración SDDM existente: ${sddm_conf}"
  fi
  if [[ "${sddm_needs_update}" == 1 ]]; then
    # InputMethod= disables qtvirtualkeyboard. Do not set QT_IM_MODULE=compose:
    # compose can swallow Enter on password submit on some keyboards/IME stacks.
    printf '[General]\nNumlock=on\nInputMethod=\n\n[Theme]\nCurrent=aidycos\n' | sudo tee "${sddm_conf}" >/dev/null
  fi

  # SDDM must not wait on pam_fprintd (common-auth) or password login freezes 10–30s.
  local sddm_pam=/etc/pam.d/sddm
  local sddm_pam_source="${ROOT}/packaging/pam/sddm"
  if [[ -f "${sddm_pam_source}" ]]; then
    if [[ ! -e "${sddm_pam}" ]] || ! sudo cmp -s "${sddm_pam_source}" "${sddm_pam}"; then
      if [[ -e "${sddm_pam}" ]] && ! sudo grep -q 'Managed by AidyCOS' "${sddm_pam}"; then
        sudo cp -a "${sddm_pam}" "${sddm_pam}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
        echo "Se respaldó PAM de SDDM: ${sddm_pam}"
      fi
      sudo install -m 0644 "${sddm_pam_source}" "${sddm_pam}"
      echo "SDDM usa autenticación por contraseña sin espera de huella."
    fi
  fi
  if [[ "${PROFILE_REFRESH}" != 1 || "${sddm_needs_update}" == 1 ]]; then
    echo "SDDM usa el tema AidyCOS con logo y formulario de acceso en cada pantalla y NumLock activo."
  fi
}
configure_login

# Start the daily GitHub check only after the full profile install is complete.
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user enable --now aidycos-update-check.timer >/dev/null 2>&1 || true

sudo install -d -m 0755 /var/lib/aidycos
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | sudo tee /var/lib/aidycos/profile-installed >/dev/null

if [[ "${PROFILE_REFRESH}" == 1 ]]; then
  echo "AidyCOS actualizado."
else
  cat <<EOF

AidyCOS quedó aplicado sobre Debian 13.
GRUB queda oculto en modo gráfico (con resoluciones de respaldo; prioriza el monitor externo si estaba conectado al aplicar el perfil). Plymouth muestra solo el logo AidyCOS y SDDM muestra logo y formulario de acceso en cada pantalla.
En SDDM selecciona la sesión Hyprland la primera vez; luego se recordará. NumLock queda activo en SDDM y Hyprland. Si se modificó tu configuración de Hyprland, revisa el respaldo indicado arriba.
Si el perfil no te sirve, quítalo con «Quitar AidyCOS» en el menú, \`aidycos-uninstall\` o \`aidycos uninstall\`.
EOF
fi

if [[ "${NO_REBOOT}" == 1 ]]; then
  if [[ "${PROFILE_REFRESH}" != 1 ]]; then
    echo "Reinicio omitido por --no-reboot."
  fi
  exit 0
fi

echo "La instalación terminó correctamente. El equipo se reiniciará en 15 segundos; pulsa Ctrl+C para cancelar."
sleep 15
sudo systemctl reboot
