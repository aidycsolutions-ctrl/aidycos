#!/usr/bin/env bash
# Remove the AidyCOS desktop profile and restore the previous login/boot/network
# settings when backups are available. Keeps personal data and, by default,
# leaves Debian packages installed so the machine stays usable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Optional fake root for tests (absolute path). Production leaves this empty.
SYSROOT="${AIDYCOS_SYSROOT:-}"
DRY_RUN=0
YES=0
NO_REBOOT=0
REMOVE_PACKAGES=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) YES=1 ;;
    --no-reboot) NO_REBOOT=1 ;;
    --remove-packages) REMOVE_PACKAGES=1 ;;
    -h|--help)
      cat <<'EOF'
Uso: uninstall-debian-profile.sh [--dry-run] [--yes] [--no-reboot] [--remove-packages]

Quita el perfil AidyCOS y, cuando hay respaldos, restaura:
  * gestor de pantalla anterior (SDDM → el que había)
  * GRUB / Plymouth
  * interfaces de red ifupdown
  * archivos de configuración con copia *.aidycos-backup*

Conserva datos de usuario (AidyC, AidyChat, documentos). Por defecto no
desinstala paquetes Debian; usa --remove-packages para quitar Hyprland/SDDM
del perfil (solo si restauras otro gestor de pantalla, o con confirmación).
EOF
      exit 0
      ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

sys() {
  local path="$1"
  if [[ -n "${SYSROOT}" ]]; then
    printf '%s%s\n' "${SYSROOT}" "${path}"
  else
    printf '%s\n' "${path}"
  fi
}

run_root() {
  if [[ "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] $*"
    return 0
  fi
  if [[ -n "${SYSROOT}" ]]; then
    # Tests operate inside SYSROOT without sudo.
    "$@"
    return 0
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# Prefer the invoking user for paths under $HOME so restores stay user-owned.
run_for_path() {
  local path="$1"
  shift
  if [[ -n "${SYSROOT}" || "${DRY_RUN}" == 1 ]]; then
    if [[ "${DRY_RUN}" == 1 ]]; then
      echo "[dry-run] $*"
      return 0
    fi
    "$@"
    return 0
  fi
  case "${path}" in
    "${HOME}"|"${HOME}"/*)
      "$@"
      ;;
    *)
      run_root "$@"
      ;;
  esac
}

log() { printf '%s\n' "$*"; }

oldest_backup() {
  local base="$1"
  local candidate=""
  local best=""
  shopt -s nullglob
  for candidate in "${base}".aidycos-backup "${base}".aidycos-backup-*; do
    [[ -e "${candidate}" ]] || continue
    if [[ -z "${best}" || "${candidate}" < "${best}" ]]; then
      best="${candidate}"
    fi
  done
  shopt -u nullglob
  [[ -n "${best}" ]] || return 1
  printf '%s\n' "${best}"
}

restore_from_backup() {
  local target="$1"
  local backup=""
  backup="$(oldest_backup "${target}" 2>/dev/null || true)"
  if [[ -z "${backup}" ]]; then
    return 1
  fi
  if [[ "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] restaurar ${target} desde ${backup}"
    return 0
  fi
  run_for_path "${target}" cp -a "${backup}" "${target}"
  log "Restaurado ${target} desde ${backup}"
  return 0
}

remove_path() {
  local path="$1"
  [[ -e "${path}" || -L "${path}" ]] || return 0
  if [[ "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] rm -rf ${path}"
    return 0
  fi
  run_for_path "${path}" rm -rf "${path}"
  log "Eliminado ${path}"
}

find_sbin() {
  local name="$1" candidate
  for candidate in "$(command -v "${name}" 2>/dev/null || true)" "/usr/sbin/${name}" "/sbin/${name}"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

confirm() {
  if [[ "${YES}" == 1 || "${DRY_RUN}" == 1 ]]; then
    return 0
  fi
  cat <<'EOF'
Esto quitará el escritorio AidyCOS (Jugoo, tema SDDM/Plymouth, atajos Hyprland,
actualizador y herramientas instaladas por el perfil) y restaurará respaldos
cuando existan. Tus archivos personales y datos de AidyC/AidyChat se conservan.

Escribe «quitar» para continuar:
EOF
  local answer=""
  read -r answer
  if [[ "${answer}" != "quitar" ]]; then
    echo "Cancelado." >&2
    exit 1
  fi
}

aidycos_ensure_admin() {
  if [[ -n "${SYSROOT}" || "${DRY_RUN}" == 1 ]]; then
    return 0
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    return 0
  fi
  if ! command -v sudo >/dev/null; then
    echo "Se necesita sudo para desinstalar el perfil." >&2
    exit 1
  fi
  if sudo -n true 2>/dev/null || sudo -v 2>/dev/null; then
    return 0
  fi
  echo "No se pudo obtener privilegios de administrador." >&2
  exit 1
}

preview() {
  cat <<'EOF'
Vista previa: quitar perfil AidyCOS
  * Detener temporizadores/servicios de usuario de AidyCOS.
  * Restaurar el gestor de pantalla guardado en /var/lib/aidycos/previous-display-manager.
  * Quitar tema SDDM AidyCOS y restaurar PAM/SDDM desde respaldo si existe.
  * Restaurar GRUB (/etc/default/grub.aidycos-backup) y quitar splash Plymouth AidyCOS.
  * Restaurar /etc/network/interfaces* desde respaldos y quitar drop-ins NM de AidyCOS.
  * Quitar Jugoo/AidyChat/AidyShip del perfil, lanzadores y /usr/local/bin/aidycos-*.
  * Restaurar o limpiar ajustes Hyprland tocados por AidyCOS.
  * Quitar fuentes APT aidycos-*.sources si las añadió el perfil.
  * Conservar datos de usuario; por defecto no hace apt remove de paquetes.
EOF
  if [[ "${REMOVE_PACKAGES}" == 1 ]]; then
    echo "  * Además: apt remove de Hyprland (y SDDM si se restauró otro gestor)."
  fi
}

stop_user_units() {
  if [[ -n "${SYSROOT}" ]]; then
    return 0
  fi
  systemctl --user disable --now aidycos-update-check.timer >/dev/null 2>&1 || true
  systemctl --user disable --now aidycos-update-check.service >/dev/null 2>&1 || true
  systemctl --user disable --now aidylink.service >/dev/null 2>&1 || true
  systemctl --user try-stop jugoo-task-watcher.service >/dev/null 2>&1 || true
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}

restore_display_manager() {
  local marker previous dm_link current
  marker="$(sys /var/lib/aidycos/previous-display-manager)"
  dm_link="$(sys /etc/systemd/system/display-manager.service)"
  previous=""
  if [[ -f "${marker}" ]]; then
    previous="$(tr -d '[:space:]' <"${marker}" || true)"
  fi
  if [[ -z "${previous}" ]]; then
    log "No hay gestor de pantalla anterior guardado; se deja el actual sin tema AidyCOS."
    return 0
  fi
  if [[ "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] restaurar display-manager → ${previous}"
    return 0
  fi
  if [[ -n "${SYSROOT}" ]]; then
    mkdir -p "$(dirname "${dm_link}")"
    ln -sfn "/lib/systemd/system/${previous}" "${dm_link}"
    log "Enlace de display-manager apuntado a ${previous} (sysroot)."
    return 0
  fi
  if systemctl list-unit-files "${previous}" >/dev/null 2>&1; then
    run_root systemctl disable sddm.service >/dev/null 2>&1 || true
    if [[ -L "${dm_link}" || -e "${dm_link}" ]]; then
      current="$(readlink "${dm_link}" 2>/dev/null || true)"
      if [[ "${current}" == *sddm.service ]]; then
        run_root rm -f "${dm_link}"
      fi
    fi
    run_root systemctl enable "${previous}" >/dev/null 2>&1 || true
    log "Gestor de pantalla restaurado: ${previous}"
  else
    log "Aviso: la unidad ${previous} ya no está instalada; no se cambió el display-manager."
  fi
}

restore_sddm_and_pam() {
  local sddm_conf sddm_pam theme_dir
  sddm_conf="$(sys /etc/sddm.conf.d/99-aidycos.conf)"
  sddm_pam="$(sys /etc/pam.d/sddm)"
  theme_dir="$(sys /usr/share/sddm/themes/aidycos)"
  if ! restore_from_backup "${sddm_conf}"; then
    remove_path "${sddm_conf}"
  fi
  restore_from_backup "${sddm_pam}" || true
  remove_path "${theme_dir}"
}

restore_boot() {
  local grub grub_dropin plymouth_conf fb_conf theme_dir bg default_link
  local update_grub update_initramfs plymouth_set
  grub="$(sys /etc/default/grub)"
  grub_dropin="$(sys /etc/default/grub.d/zz-aidycos.cfg)"
  plymouth_conf="$(sys /etc/plymouth/plymouthd.conf)"
  fb_conf="$(sys /etc/initramfs-tools/conf.d/aidycos-framebuffer)"
  theme_dir="$(sys /usr/share/plymouth/themes/aidycos)"
  bg="$(sys /boot/grub/AidyCOS.png)"
  default_link="$(sys /usr/share/plymouth/themes/default.plymouth)"

  restore_from_backup "${grub}" || true
  remove_path "${grub_dropin}"
  if [[ -f "$(sys /etc/default/grub.d/aidyc.cfg.disabled)" ]]; then
    if [[ "${DRY_RUN}" == 1 ]]; then
      echo "[dry-run] rehabilitar aidyc.cfg.disabled"
    else
      run_root mv -f "$(sys /etc/default/grub.d/aidyc.cfg.disabled)" "$(sys /etc/default/grub.d/aidyc.cfg)"
    fi
  fi
  if restore_from_backup "${plymouth_conf}"; then
    :
  else
    remove_path "${plymouth_conf}"
  fi
  remove_path "${fb_conf}"
  remove_path "${theme_dir}"
  remove_path "${bg}"
  remove_path "$(sys /usr/share/backgrounds/aidycos.png)"
  if [[ -L "${default_link}" ]]; then
    local target
    target="$(readlink "${default_link}" 2>/dev/null || true)"
    if [[ "${target}" == *aidycos* ]]; then
      remove_path "${default_link}"
    fi
  fi
  # Restore quiet_boot generator if we changed it.
  local linux_gen
  linux_gen="$(sys /etc/grub.d/10_linux)"
  restore_from_backup "${linux_gen}" || true

  if [[ -n "${SYSROOT}" || "${DRY_RUN}" == 1 ]]; then
    return 0
  fi
  update_grub="$(find_sbin update-grub || true)"
  update_initramfs="$(find_sbin update-initramfs || true)"
  plymouth_set="$(find_sbin plymouth-set-default-theme || true)"
  if [[ -n "${plymouth_set}" ]]; then
    run_root "${plymouth_set}" -r || true
  fi
  if [[ -n "${update_grub}" && -f /etc/default/grub ]]; then
    run_root "${update_grub}" || true
  fi
  if [[ -n "${update_initramfs}" ]]; then
    run_root "${update_initramfs}" -u -k all || true
  fi
  log "Arranque GRUB/Plymouth restaurado (sin splash AidyCOS)."
}

restore_network() {
  local interfaces interfaces_d nm_managed nm_wifi marker reclaim_unit reclaim_script
  interfaces="$(sys /etc/network/interfaces)"
  interfaces_d="$(sys /etc/network/interfaces.d)"
  nm_managed="$(sys /etc/NetworkManager/conf.d/99-aidycos-ifupdown.conf)"
  nm_wifi="$(sys /etc/NetworkManager/conf.d/99-aidycos-wifi.conf)"
  marker="$(sys /var/lib/aidycos/network-migrated)"
  reclaim_unit="$(sys /etc/systemd/system/aidycos-wifi-reclaim.service)"
  reclaim_script="$(sys /usr/local/libexec/aidycos/aidycos-wifi-reclaim.sh)"

  restore_from_backup "${interfaces}" || true
  if [[ -d "${interfaces_d}" ]]; then
    local backup dest
    shopt -s nullglob
    for backup in "${interfaces_d}"/*.aidycos-backup "${interfaces_d}"/*.aidycos-backup-*; do
      [[ -e "${backup}" ]] || continue
      dest="${backup%.aidycos-backup*}"
      if [[ "${dest}" == "${backup}" ]]; then
        continue
      fi
      if [[ "${DRY_RUN}" == 1 ]]; then
        echo "[dry-run] restaurar ${dest} desde ${backup}"
      else
        run_root cp -a "${backup}" "${dest}"
        log "Restaurado ${dest} desde ${backup}"
      fi
    done
    shopt -u nullglob
  fi
  remove_path "${nm_managed}"
  remove_path "${nm_wifi}"
  remove_path "${marker}"
  if [[ -z "${SYSROOT}" && "${DRY_RUN}" != 1 ]]; then
    run_root systemctl disable --now aidycos-wifi-reclaim.service >/dev/null 2>&1 || true
  fi
  remove_path "${reclaim_unit}"
  remove_path "${reclaim_script}"
  if [[ -z "${SYSROOT}" && "${DRY_RUN}" != 1 ]]; then
    run_root systemctl unmask networking.service >/dev/null 2>&1 || true
    run_root systemctl unmask 'wpa_supplicant@.service' >/dev/null 2>&1 || true
    run_root systemctl daemon-reload >/dev/null 2>&1 || true
    run_root systemctl try-reload-or-restart NetworkManager.service >/dev/null 2>&1 || true
  fi
  log "Red: drop-ins AidyCOS quitados; interfaces restauradas si había respaldo."
}

remove_system_binaries() {
  local path
  for path in \
    /usr/local/bin/jugoo \
    /usr/local/bin/aidyc \
    /usr/local/bin/aidyc-update \
    /usr/local/bin/aidylink \
    /usr/local/bin/aidyship \
    /usr/local/bin/aidycos-onlyoffice \
    /usr/local/bin/aidycos-download-dir \
    /usr/local/bin/aidycos-prefer-external-display \
    /usr/local/bin/aidycos-boot-gfxmode \
    /usr/local/bin/aidycos-grub-background \
    /usr/local/bin/aidycos-uninstall \
    /usr/local/bin/aidycos-update
  do
    remove_path "$(sys "${path}")"
  done
  remove_path "$(sys /usr/local/libexec/aidycos)"
  remove_path "$(sys /usr/share/applications/aidychat.desktop)"
  remove_path "$(sys /usr/share/applications/aidyship.desktop)"
  remove_path "$(sys /usr/share/pixmaps/aidyc.png)"
  remove_path "$(sys /usr/share/pixmaps/aidychat.png)"
  remove_path "$(sys /usr/share/pixmaps/aidyship.png)"
  local size
  for size in 16 24 32 48 64 128 256 512; do
    remove_path "$(sys /usr/share/icons/hicolor/${size}x${size}/apps/aidyc.png)"
    remove_path "$(sys /usr/share/icons/hicolor/${size}x${size}/apps/aidychat.png)"
    remove_path "$(sys /usr/share/icons/hicolor/${size}x${size}/apps/aidyship.png)"
  done
}

restore_or_remove_jugoo() {
  local jugoo preserved
  jugoo="$(sys /opt/aidyc/jugoo)"
  preserved="$(sys /opt/aidyc/jugoo.aidycos-preserved)"
  if [[ -e "${preserved}" || -L "${preserved}" ]]; then
    if [[ "${DRY_RUN}" == 1 ]]; then
      echo "[dry-run] restaurar Jugoo preservado → ${jugoo}"
    else
      remove_path "${jugoo}"
      run_root mv "${preserved}" "${jugoo}"
      log "Se restauró Jugoo previo en ${jugoo}"
    fi
  else
    remove_path "${jugoo}"
  fi
  remove_path "$(sys /opt/aidyc/aidylink)"
  remove_path "$(sys /opt/aidyc/aidyship)"
  # Keep /opt/aidyc if AidyC or other apps remain.
  if [[ -d "$(sys /opt/aidyc)" ]]; then
    if [[ -z "$(find "$(sys /opt/aidyc)" -mindepth 1 -maxdepth 1 2>/dev/null | head -n1)" ]]; then
      remove_path "$(sys /opt/aidyc)"
    fi
  fi
}

strip_hypr_aidycos_lines() {
  local file="$1"
  [[ -f "${file}" ]] || return 0
  if [[ "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] limpiar referencias AidyCOS en ${file}"
    return 0
  fi
  # Drop managed source/exec lines; leave the rest of the user's config.
  sed -i \
    -e '\|^[[:space:]]*source[[:space:]]*=.*aidycos\.conf[[:space:]]*$|d' \
    -e '\|^[[:space:]]*exec-once[[:space:]]*=.*/usr/local/bin/jugoo[[:space:]]*$|d' \
    -e '\|^[[:space:]]*# AidyCOS.*$|d' \
    "${file}" || true
}

restore_hyprland_user() {
  local home config_home hypr_dir hypr_conf aidycos_conf
  home="${HOME}"
  if [[ -n "${SYSROOT}" ]]; then
    home="$(sys /home/testuser)"
    mkdir -p "${home}"
    config_home="${home}/.config"
  else
    config_home="${XDG_CONFIG_HOME:-${home}/.config}"
  fi
  hypr_dir="${config_home}/hypr"
  hypr_conf="${hypr_dir}/hyprland.conf"
  aidycos_conf="${hypr_dir}/aidycos.conf"

  if restore_from_backup "${hypr_conf}"; then
    :
  else
    strip_hypr_aidycos_lines "${hypr_conf}"
  fi
  # aidycos.conf is owned by the profile; restore oldest backup or remove.
  if ! restore_from_backup "${aidycos_conf}"; then
    remove_path "${aidycos_conf}"
  fi
  remove_path "${hypr_dir}/config/jugoo_ventanas.conf"
  remove_path "${hypr_dir}/config/jugoo_hyprbars.conf"
  remove_path "${hypr_dir}/scripts/ventanas"
  remove_path "${hypr_dir}/scripts/ventanas.py"
  remove_path "${hypr_dir}/scripts/decoraciones.py"
}

remove_user_bits() {
  local home data_home config_home desktop_dir apps icons bin_dir
  home="${HOME}"
  if [[ -n "${SYSROOT}" ]]; then
    home="$(sys /home/testuser)"
    data_home="${home}/.local/share"
    config_home="${home}/.config"
  else
    data_home="${XDG_DATA_HOME:-${home}/.local/share}"
    config_home="${XDG_CONFIG_HOME:-${home}/.config}"
  fi
  apps="${data_home}/applications"
  icons="${data_home}/icons/hicolor"
  bin_dir="${home}/.local/bin"
  desktop_dir=""
  if command -v xdg-user-dir >/dev/null 2>&1 && [[ -z "${SYSROOT}" ]]; then
    desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -z "${desktop_dir}" || "${desktop_dir}" == "${home}" ]]; then
    if [[ -d "${home}/Desktop" ]]; then
      desktop_dir="${home}/Desktop"
    elif [[ -d "${home}/Escritorio" ]]; then
      desktop_dir="${home}/Escritorio"
    else
      desktop_dir="${home}/Desktop"
    fi
  fi

  local name
  for name in \
    aidycos-update.desktop \
    aidycos-uninstall.desktop \
    aidyc-update.desktop \
    aidycos-impresoras.desktop \
    aidycos-paquetes.desktop \
    aidycos-onlyoffice.desktop \
    aidyc.desktop \
    aidychat.desktop \
    aidyship.desktop \
    aidylink.desktop
  do
    remove_path "${apps}/${name}"
    remove_path "${desktop_dir}/AidyChat.desktop"
    remove_path "${desktop_dir}/${name}"
  done
  remove_path "${desktop_dir}/AidyChat.desktop"

  local size
  for size in 16 24 32 48 64 128 256 512; do
    remove_path "${icons}/${size}x${size}/apps/aidyc.png"
    remove_path "${icons}/${size}x${size}/apps/aidychat.png"
    remove_path "${icons}/${size}x${size}/apps/aidyship.png"
  done

  for name in \
    jugoo \
    captura.sh \
    aidycos \
    aidycos-update \
    aidycos-uninstall \
    aidylink \
    aidyship
  do
    # Prefer restoring user jugoo backup if present.
    if [[ "${name}" == jugoo && -e "${bin_dir}/jugoo.aidycos-backup" ]]; then
      if [[ "${DRY_RUN}" == 1 ]]; then
        echo "[dry-run] restaurar ${bin_dir}/jugoo desde backup"
      else
        cp -a "${bin_dir}/jugoo.aidycos-backup" "${bin_dir}/jugoo"
        log "Restaurado ${bin_dir}/jugoo desde backup"
      fi
    else
      remove_path "${bin_dir}/${name}"
    fi
  done
  # captura.sh may have timestamped backups; leave backups, remove managed script.
  remove_path "${bin_dir}/captura.sh"

  remove_path "${config_home}/systemd/user/aidycos-update-check.service"
  remove_path "${config_home}/systemd/user/aidycos-update-check.timer"
  remove_path "${config_home}/systemd/user/aidylink.service"
  remove_path "${config_home}/systemd/user/jugoo-task-watcher.service.d/aidycos.conf"
  remove_path "${data_home}/aidycos/patches"
  remove_path "${data_home}/aidycos/venv"
  remove_path "${data_home}/aidycos/github-commit"
  # Keep shared-printers.json and other user data under aidycos/ if present.
}

remove_apt_sources() {
  local path listed
  for path in \
    "$(sys /etc/apt/sources.list.d/aidycos-debian.sources)" \
    "$(sys /etc/apt/sources.list.d/aidycos-backports.sources)"
  do
    remove_path "${path}"
  done
  listed="$(sys /var/lib/aidycos/created-apt-sources)"
  if [[ -f "${listed}" ]]; then
    while IFS= read -r path || [[ -n "${path}" ]]; do
      [[ -n "${path}" ]] || continue
      remove_path "$(sys "${path}")"
    done <"${listed}"
  fi
}

remove_misc_system() {
  local override thunar_xml sudoers
  override="$(sys /etc/systemd/system/cups-browsed.service.d/aidycos.conf)"
  thunar_xml="$(sys /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar-volman.xml)"
  sudoers="$(sys /etc/sudoers.d/10-aidycos-sudo)"
  remove_path "${override}"
  # Only remove thunar-volman xml if it is the AidyCOS-managed copy; if unsure, leave it.
  if [[ -f "${thunar_xml}" ]] && grep -q 'aidycos\|AidyCOS\|automount' "${thunar_xml}" 2>/dev/null; then
    remove_path "${thunar_xml}"
  fi
  # Leave sudoers rule: removing it can lock out a user that only gained sudo via AidyCOS.
  # Documented; do not delete "${sudoers}" by default.
  :
  remove_path "$(sys /var/lib/aidycos/legacy-aidyc-cleaned)"
  remove_path "$(sys /var/lib/aidycos/previous-display-manager)"
  remove_path "$(sys /var/lib/aidycos/profile-installed)"
  remove_path "$(sys /var/lib/aidycos/created-apt-sources)"
  # network-migrated already removed in restore_network
  if [[ -d "$(sys /var/lib/aidycos)" ]]; then
    if [[ -z "$(find "$(sys /var/lib/aidycos)" -mindepth 1 -maxdepth 1 2>/dev/null | head -n1)" ]]; then
      remove_path "$(sys /var/lib/aidycos)"
    fi
  fi
}

maybe_remove_packages() {
  if [[ "${REMOVE_PACKAGES}" != 1 ]]; then
    return 0
  fi
  if [[ -n "${SYSROOT}" || "${DRY_RUN}" == 1 ]]; then
    echo "[dry-run] apt-get remove hyprland stack (+ sddm si hay DM previo)"
    return 0
  fi
  local pkgs=(
    hyprland
    xdg-desktop-portal-hyprland
    hyprland-guiutils
    hyprpolkitagent
    hyprland-protocols
  )
  local marker previous
  marker="$(sys /var/lib/aidycos/previous-display-manager)"
  previous=""
  # Marker may already be deleted; check before remove_misc if needed — call this before.
  if [[ -f "${marker}" ]]; then
    previous="$(tr -d '[:space:]' <"${marker}" || true)"
  fi
  if [[ -n "${previous}" ]]; then
    pkgs+=(sddm)
  fi
  export DEBIAN_FRONTEND=noninteractive
  run_root apt-get remove -y --purge "${pkgs[@]}" || true
  run_root apt-get autoremove -y || true
  log "Paquetes del perfil de escritorio eliminados (donde era seguro)."
}

# --- main ---
if [[ -z "${SYSROOT}" && "${DRY_RUN}" != 1 ]]; then
  if [[ ! -r /etc/os-release ]]; then
    echo "No se puede identificar la distribución." >&2
    exit 1
  fi
fi

if [[ "${DRY_RUN}" == 1 ]]; then
  preview
  if [[ -n "${SYSROOT}" ]]; then
    # Continue into helpers against the fake root so tests can assert side effects
    # without requiring confirmation.
    :
  else
    exit 0
  fi
fi

aidycos_ensure_admin
confirm

stop_user_units
restore_display_manager
# Apt remove needs the previous-DM marker (still on disk until remove_misc_system).
maybe_remove_packages
restore_sddm_and_pam
restore_boot
restore_network
remove_system_binaries
restore_or_remove_jugoo
restore_hyprland_user
remove_user_bits
remove_apt_sources
remove_misc_system

if [[ -z "${SYSROOT}" ]]; then
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
  fi
fi

cat <<'EOF'

AidyCOS se quitó del perfil de este equipo.
Si había un gestor de pantalla anterior, debería volver tras reiniciar.
Los datos personales y de AidyC/AidyChat se conservaron.
Si el equipo quedó sin escritorio, puedes instalar uno de Debian, por ejemplo:
  sudo apt install task-gnome-desktop
EOF

if [[ "${NO_REBOOT}" == 1 || "${DRY_RUN}" == 1 || -n "${SYSROOT}" ]]; then
  echo "Reinicio omitido."
  exit 0
fi

echo "El equipo se reiniciará en 15 segundos; pulsa Ctrl+C para cancelar."
sleep 15
run_root systemctl reboot
