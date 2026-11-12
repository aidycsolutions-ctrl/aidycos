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
  * Habilitar NetworkManager y UPower para los indicadores de Wi-Fi y batería de Jugoo.
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
  * Activar NumLock en la pantalla de acceso y en Hyprland.
  * Crear configuración inicial de Hyprland si no existe.
  * Ocultar GRUB y los mensajes de arranque; mostrar el logo en Plymouth y SDDM.
  * Retrasar cups-browsed hasta el entorno gráfico.
  * Instalar el gestor de impresoras y Alt+F4 para el menú de apagado.
  * Mantener usuario, contraseña y autologin actuales; cambiar el gestor de sesión a SDDM y respaldar los ajustes Hyprland tocados.
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
  hyprland xdg-desktop-portal-hyprland hyprland-guiutils hyprpolkitagent
sudo apt-get install -y --no-install-recommends plymouth plymouth-themes
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

  sudo install -D -m 0755 "${ROOT}/packaging/jugoo-launcher" /usr/local/bin/jugoo
  # Parche de iconos AidyC/AidyChat en Jugoo sin tocar /opt si el overlay ya lo trajo.
  install -d "${HOME}/.local/share/aidycos/patches"
  install -m 0644 "${ROOT}/packaging/jugoo-overlay/shell/icons.py" \
    "${HOME}/.local/share/aidycos/patches/icons.py"
  if [[ -f "${ROOT}/packaging/jugoo-overlay/patches/jugoo_aidycos_boot.py" ]]; then
    install -m 0644 "${ROOT}/packaging/jugoo-overlay/patches/jugoo_aidycos_boot.py" \
      "${HOME}/.local/share/aidycos/patches/jugoo_aidycos_boot.py"
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
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
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
  (cd "${jugoo_dir}" && python3 -m shell --install)
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
  install -D -m 0644 "${ROOT}/packaging/systemd/jugoo-task-watcher.service.d/aidycos.conf" \
    "${service_dir}/aidycos.conf"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  systemctl --user try-restart jugoo-task-watcher.service >/dev/null 2>&1 || true
  # hyprbars is owned by AidyCOS (packaging/hyprland/setup-hyprbars.sh) and runs
  # after the ventanas scripts are installed further below — Jugoo upstream does
  # not ship setup-hyprbars on the branches we clone.
}
install_jugoo

# Separate AidyC updater: the dock icon opens an installed copy, so updates
# need an explicit launcher that checks GitHub and compares Debian versions.
sudo install -m 0755 "${ROOT}/scripts/aidyc-update" /usr/local/bin/aidyc-update
sudo install -m 0755 "${ROOT}/scripts/aidycos-onlyoffice" /usr/local/bin/aidycos-onlyoffice
install -D -m 0644 "${ROOT}/packaging/applications/aidyc-update.desktop" \
  "${HOME}/.local/share/applications/aidyc-update.desktop"
# Friendly Spanish entry for the CUPS printer manager.
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-impresoras.desktop" \
  "${HOME}/.local/share/applications/aidycos-impresoras.desktop"
# Synaptic + OnlyOffice helpers so users can install office and other apps.
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-paquetes.desktop" \
  "${HOME}/.local/share/applications/aidycos-paquetes.desktop"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-onlyoffice.desktop" \
  "${HOME}/.local/share/applications/aidycos-onlyoffice.desktop"
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
if [[ -f "${printer_catalog_src}" ]]; then
  install -D -m 0644 "${printer_catalog_src}" "${printer_catalog_dst}"
  docs_dir="$(xdg-user-dir DOCUMENTS 2>/dev/null || true)"
  if [[ -n "${docs_dir}" && -d "${docs_dir}" ]]; then
    install -D -m 0644 "${printer_catalog_src}" "${docs_dir}/shared-printers.json"
  fi
  echo "Catálogo de impresoras AidyCOS listo en ${printer_catalog_dst}"
  if [[ -f "${ROOT}/scripts/apply-shared-printers.py" ]]; then
    if python3 "${ROOT}/scripts/apply-shared-printers.py" "${printer_catalog_dst}"; then
      echo "Impresoras compartidas aplicadas desde el catálogo AidyCOS."
    else
      echo "Aviso: no se pudieron aplicar las impresoras del catálogo (¿CUPS/lpadmin?)." >&2
    fi
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
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  sudo gtk-update-icon-cache -f /usr/share/icons/Adwaita >/dev/null 2>&1 || true
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# Jugoo's network and battery indicators use NetworkManager and UPower.
# wpasupplicant (+ iw/rfkill/wireless firmware) comes from the aidyc-desktop
# module packages list; do not install a conflicting wpa_supplicant stack here.
# Migrate Debian-installer ifupdown Wi-Fi into NM so the bar does not show "LAN".
bash "${ROOT}/packaging/network/apply-aidycos-network.sh"
sudo systemctl enable --now upower.service

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
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    update-desktop-database "${desktop_dir}" >/dev/null 2>&1 || true
  fi
  echo "AidyChat instalado. Abre el acceso del escritorio; la primera vez pide el nombre del PC y puedes emparejar otros con un código."
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
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    sudo gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
  if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    update-desktop-database "${desktop_dir}" >/dev/null 2>&1 || true
  fi
  echo "AidyShip instalado. Abre el menú o Super+G; la primera vez pide conectar tu GitHub."
}
install_aidyship

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

# Title-bar buttons: compile hyprbars here (not via Jugoo). Needs network +
# hyprland-dev from backports; without this the test laptop has no min/close.
if ! bash "${ROOT}/packaging/hyprland/setup-hyprbars.sh"; then
  echo "ERROR: no se pudieron instalar los botones de título (hyprbars)." >&2
  echo "Sin ~/.local/lib/jugoo/hyprbars.so las ventanas no muestran minimizar/cerrar." >&2
  echo "Revisa red, hyprland-dev (trixie-backports) y vuelve a aplicar el perfil." >&2
fi
if [[ ! -e "${HYPR_AIDYCOS_CONF}" ]]; then
  cat >"${HYPR_AIDYCOS_CONF}" <<'EOF'
# AidyCOS keyboard and Jugoo defaults.
env = XDG_CURRENT_DESKTOP,Hyprland
env = XDG_SESSION_TYPE,wayland
input {
    numlock_by_default = true
}
bind = SUPER, SPACE, exec, jugoo action launcher
bind = SUPER, E, exec, /usr/bin/env GDK_BACKEND=wayland /usr/bin/thunar
bind = SUPER, G, exec, aidyship ui
bind = , Print, exec, ~/.local/bin/captura.sh
bind = ALT, F4, exec, jugoo action session
bind = SUPER, LEFT, workspace, -1
bind = SUPER, RIGHT, workspace, +1
bind = SUPER, Y, workspace, +1
bind = SUPER SHIFT, U, exec, aidycos-update --check
exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DISPLAY
exec-once = /usr/local/bin/aidycos-prefer-external-display
exec-once = /usr/bin/thunar --daemon
exec-once = /usr/local/bin/aidycos-download-dir ensure
exec-once = /usr/local/bin/aidycos-download-dir watch
EOF
  printf 'exec-once = %s\n' "${POLKIT_AGENT}" >>"${HYPR_AIDYCOS_CONF}"
else
  missing=0
  grep -qE '^[[:space:]]*numlock_by_default[[:space:]]*=[[:space:]]*true' "${HYPR_AIDYCOS_CONF}" || missing=1
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
  grep -qF 'bind = SUPER, LEFT, workspace, -1' "${HYPR_AIDYCOS_CONF}" || grep -qF 'bind = SUPER, LEFT, workspace, -1' "${HYPR_CONF}" 2>/dev/null || missing=1
  grep -qF 'bind = SUPER, RIGHT, workspace, +1' "${HYPR_AIDYCOS_CONF}" || grep -qF 'bind = SUPER, RIGHT, workspace, +1' "${HYPR_CONF}" 2>/dev/null || missing=1
  grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_AIDYCOS_CONF}" || grep -qF 'bind = SUPER, Y, workspace, +1' "${HYPR_CONF}" 2>/dev/null || missing=1
  # Super+C is reserved for Cursor (hyprland.conf); strip any old AidyChat bind.
  if grep -qE '^[[:space:]]*bind[[:space:]]*=[[:space:]]*SUPER,[[:space:]]*C,[[:space:]]*exec,[[:space:]]*aidylink ui' "${HYPR_AIDYCOS_CONF}"; then
    missing=1
  fi
  grep -qF 'exec-once = /usr/local/bin/aidycos-prefer-external-display' "${HYPR_AIDYCOS_CONF}" || missing=1
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
}
EOF
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
    if ! grep -qF 'bind = SUPER, LEFT, workspace, -1' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qF 'bind = SUPER, LEFT, workspace, -1' "${HYPR_CONF}"; }; then
      printf 'bind = SUPER, LEFT, workspace, -1\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
    if ! grep -qF 'bind = SUPER, RIGHT, workspace, +1' "${HYPR_AIDYCOS_CONF}" \
       && { [[ ! -f "${HYPR_CONF}" ]] || ! grep -qF 'bind = SUPER, RIGHT, workspace, +1' "${HYPR_CONF}"; }; then
      printf 'bind = SUPER, RIGHT, workspace, +1\n' >>"${HYPR_AIDYCOS_CONF}"
    fi
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

if [[ ! -e "${HYPR_CONF}" ]]; then
  cat >"${HYPR_CONF}" <<'EOF'
# AidyCOS: configuración base compatible con el perfil inicial.
source = ~/.config/hypr/aidycos.conf
monitor = , preferred, auto, 1
env = XDG_CURRENT_DESKTOP,Hyprland
env = XDG_SESSION_TYPE,wayland
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
exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DISPLAY
exec-once = /usr/local/bin/jugoo
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
exec-once = /usr/local/bin/jugoo
EOF
    fi
    echo "Se agregaron los ajustes AidyCOS; respaldo previo: ${backup}"
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

# Quiet boot splash: GRUB logo + Plymouth. Absolute /usr/sbin paths matter on
# Debian user PATH (update-grub is not in /usr/bin).
bash "${ROOT}/packaging/boot/apply-aidycos-boot.sh"

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
  echo "SDDM usa el tema AidyCOS con logo y formulario de acceso en cada pantalla y NumLock activo."
}
configure_login

# Start the daily GitHub check only after the full profile install is complete.
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user enable --now aidycos-update-check.timer >/dev/null 2>&1 || true

cat <<EOF

AidyCOS quedó aplicado sobre Debian 13.
GRUB queda oculto en modo gráfico (con resoluciones de respaldo; prioriza el monitor externo si estaba conectado al aplicar el perfil). Plymouth muestra solo el logo AidyCOS y SDDM muestra logo y formulario de acceso en cada pantalla.
En SDDM selecciona la sesión Hyprland la primera vez; luego se recordará. NumLock queda activo en SDDM y Hyprland. Si se modificó tu configuración de Hyprland, revisa el respaldo indicado arriba.
EOF

if [[ "${NO_REBOOT}" == 1 ]]; then
  echo "Reinicio omitido por --no-reboot."
  exit 0
fi

echo "La instalación terminó correctamente. El equipo se reiniciará en 15 segundos; pulsa Ctrl+C para cancelar."
sleep 15
sudo systemctl reboot
