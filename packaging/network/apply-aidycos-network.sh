#!/usr/bin/env bash
# Give NetworkManager ownership of Wi-Fi left on Debian ifupdown after install.
# Jugoo only talks to NetworkManager; unmanaged wlan looks like "LAN" in the bar.
set -euo pipefail

NM_CONF_D=/etc/NetworkManager/conf.d
NM_MANAGED_DROPIN="${NM_CONF_D}/99-aidycos-ifupdown.conf"
INTERFACES=/etc/network/interfaces
INTERFACES_D=/etc/network/interfaces.d
NM_CONNECTIONS=/etc/NetworkManager/system-connections
MARKER=/var/lib/aidycos/network-migrated

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

has_non_loopback_iface_config() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  grep -Eiq '^[[:space:]]*(allow-hotplug|auto)[[:space:]]+(wlan|wlp|wlx|wifi)' "${file}" \
    || grep -Eiq '^[[:space:]]*iface[[:space:]]+(wlan|wlp|wlx)[[:alnum:]:._-]*[[:space:]]+inet' "${file}" \
    || grep -Eiq '^[[:space:]]*wpa-ssid[[:space:]]+' "${file}"
}

extract_wpa_field() {
  local field="$1"
  local file="$2"
  awk -v key="${field}" '
    BEGIN { IGNORECASE=1 }
    $1 == key {
      $1 = ""
      sub(/^[[:space:]]+/, "")
      print
      exit
    }
  ' "${file}"
}

create_nm_wifi_from_interfaces() {
  local source_file="$1"
  local ssid psk uuid dest
  ssid="$(extract_wpa_field "wpa-ssid" "${source_file}")"
  psk="$(extract_wpa_field "wpa-psk" "${source_file}")"
  [[ -n "${ssid}" ]] || return 0

  run_root install -d -m 0755 "${NM_CONNECTIONS}"
  uuid="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')"
  dest="${NM_CONNECTIONS}/aidycos-${ssid//[^A-Za-z0-9._-]/_}.nmconnection"
  if run_root test -e "${dest}"; then
    return 0
  fi

  {
    printf '[connection]\nid=%s\nuuid=%s\ntype=wifi\nautoconnect=true\n\n' "${ssid}" "${uuid}"
    printf '[wifi]\nmode=infrastructure\nssid=%s\n\n' "${ssid}"
    if [[ -n "${psk}" ]]; then
      printf '[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n\n' "${psk}"
    fi
    printf '[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'
  } | run_root tee "${dest}" >/dev/null
  run_root chmod 0600 "${dest}"
  echo "Se migró la Wi-Fi «${ssid}» de ifupdown a NetworkManager."
}

backup_and_loopback_only() {
  local file="$1"
  [[ -f "${file}" ]] || return 0
  if ! has_non_loopback_iface_config "${file}"; then
    return 0
  fi
  run_root cp -a "${file}" "${file}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  create_nm_wifi_from_interfaces "${file}"
  printf 'auto lo\niface lo inet loopback\n' | run_root tee "${file}" >/dev/null
  echo "Se dejó ${file} solo con loopback; NetworkManager gestiona el resto."
}

run_root install -d -m 0755 "${NM_CONF_D}" /var/lib/aidycos
printf '%s\n' \
  '[main]' \
  'plugins=ifupdown,keyfile' \
  '' \
  '[ifupdown]' \
  'managed=true' \
  | run_root tee "${NM_MANAGED_DROPIN}" >/dev/null

if [[ ! -e "${MARKER}" ]]; then
  backup_and_loopback_only "${INTERFACES}"
  if [[ -d "${INTERFACES_D}" ]]; then
    shopt -s nullglob
    for dropin in "${INTERFACES_D}"/*; do
      [[ -f "${dropin}" ]] || continue
      [[ "$(basename "${dropin}")" == *aidycos-backup* ]] && continue
      if has_non_loopback_iface_config "${dropin}"; then
        create_nm_wifi_from_interfaces "${dropin}"
        run_root mv "${dropin}" "${dropin}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
      fi
    done
    shopt -u nullglob
  fi
  run_root install -D -m 0644 /dev/null "${MARKER}"
fi

run_root systemctl enable NetworkManager.service >/dev/null 2>&1 || true
run_root systemctl restart NetworkManager.service >/dev/null 2>&1 || true
# Prefer NM over legacy networking.service when both exist.
if systemctl list-unit-files networking.service >/dev/null 2>&1; then
  run_root systemctl disable networking.service >/dev/null 2>&1 || true
fi

echo "NetworkManager gestiona las interfaces (ifupdown managed=true)."
