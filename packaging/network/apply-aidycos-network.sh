#!/usr/bin/env bash
# Give NetworkManager ownership of Wi-Fi left on Debian ifupdown after install.
# Jugoo only talks to NetworkManager; unmanaged wlan looks unavailable / blank.
set -euo pipefail

NM_CONF_D=/etc/NetworkManager/conf.d
NM_MANAGED_DROPIN="${NM_CONF_D}/99-aidycos-ifupdown.conf"
INTERFACES=/etc/network/interfaces
INTERFACES_D=/etc/network/interfaces.d
NM_CONNECTIONS=/etc/NetworkManager/system-connections
MARKER=/var/lib/aidycos/network-migrated
WPA_SUPPLICANT_CONF=/etc/wpa_supplicant/wpa_supplicant.conf

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

create_nm_wifi_connection() {
  local ssid="$1"
  local psk="${2:-}"
  local uuid dest safe
  [[ -n "${ssid}" ]] || return 0

  run_root install -d -m 0755 "${NM_CONNECTIONS}"
  safe="$(printf '%s' "${ssid}" | tr -c 'A-Za-z0-9._-' '_')"
  dest="${NM_CONNECTIONS}/aidycos-${safe}.nmconnection"
  if run_root test -e "${dest}"; then
    return 0
  fi
  # Skip if NM already knows this SSID.
  if command -v nmcli >/dev/null 2>&1; then
    if nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep -Fxq "${ssid}:802-11-wireless"; then
      return 0
    fi
  fi

  uuid="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')"
  {
    printf '[connection]\nid=%s\nuuid=%s\ntype=wifi\nautoconnect=true\n\n' "${ssid}" "${uuid}"
    printf '[wifi]\nmode=infrastructure\nssid=%s\n\n' "${ssid}"
    if [[ -n "${psk}" ]]; then
      printf '[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n\n' "${psk}"
    fi
    printf '[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'
  } | run_root tee "${dest}" >/dev/null
  run_root chmod 0600 "${dest}"
  echo "Se creó el perfil NetworkManager para «${ssid}»."
}

create_nm_wifi_from_interfaces() {
  local source_file="$1"
  local ssid psk
  ssid="$(extract_wpa_field "wpa-ssid" "${source_file}")"
  psk="$(extract_wpa_field "wpa-psk" "${source_file}")"
  create_nm_wifi_connection "${ssid}" "${psk}"
}

import_from_wpa_supplicant_conf() {
  local conf="$1"
  [[ -f "${conf}" ]] || return 0
  python3 - "${conf}" <<'PY' | while IFS=$'\t' read -r ssid psk; do
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
for block in re.findall(r"network\s*=\s*\{(.*?)\}", text, flags=re.S):
    ssid_m = re.search(r'^\s*ssid\s*=\s*"([^"]*)"', block, flags=re.M)
    if not ssid_m:
        continue
    psk_m = re.search(r'^\s*psk\s*=\s*"([^"]*)"', block, flags=re.M)
    ssid = ssid_m.group(1)
    psk = psk_m.group(1) if psk_m else ""
    print(f"{ssid}\t{psk}")
PY
    create_nm_wifi_connection "${ssid}" "${psk}"
  done
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

claim_wifi_devices() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local line device state
  while IFS=: read -r device _type state _; do
    [[ -n "${device}" ]] || continue
    case "${state}" in
      unmanaged|unavailable)
        nmcli device set "${device}" managed yes >/dev/null 2>&1 || true
        echo "NetworkManager pasa a gestionar ${device} (antes ${state})."
        ;;
    esac
  done < <(nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '$2=="wifi"{print}')
}

adopt_current_ssid_if_needed() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local ssid=""
  if command -v iwgetid >/dev/null 2>&1; then
    ssid="$(iwgetid -r 2>/dev/null || true)"
  fi
  if [[ -z "${ssid}" ]]; then
    ssid="$(nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | awk -F: '$1=="yes"{print $2; exit}')"
  fi
  [[ -n "${ssid}" ]] || return 0
  create_nm_wifi_connection "${ssid}" ""
  # Ask NM to take the already-associated link when possible.
  nmcli connection up id "${ssid}" >/dev/null 2>&1 || true
}

run_root install -d -m 0755 "${NM_CONF_D}" /var/lib/aidycos
printf '%s\n' \
  '[main]' \
  'plugins=ifupdown,keyfile' \
  '' \
  '[ifupdown]' \
  'managed=true' \
  | run_root tee "${NM_MANAGED_DROPIN}" >/dev/null

# Also force the main conf ifupdown.managed when present.
if run_root test -f /etc/NetworkManager/NetworkManager.conf; then
  if run_root grep -q '^[[:space:]]*managed[[:space:]]*=' /etc/NetworkManager/NetworkManager.conf; then
    run_root sed -i 's/^[[:space:]]*managed[[:space:]]*=.*/managed=true/' /etc/NetworkManager/NetworkManager.conf
  fi
fi

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
  import_from_wpa_supplicant_conf "${WPA_SUPPLICANT_CONF}"
  run_root install -D -m 0644 /dev/null "${MARKER}"
fi

run_root systemctl enable NetworkManager.service >/dev/null 2>&1 || true
run_root systemctl restart NetworkManager.service >/dev/null 2>&1 || true
# Prefer NM over legacy networking.service when both exist.
if systemctl list-unit-files networking.service >/dev/null 2>&1; then
  run_root systemctl disable networking.service >/dev/null 2>&1 || true
  run_root systemctl stop networking.service >/dev/null 2>&1 || true
fi

# Always re-claim wifi devices: installer Wi-Fi often stays unmanaged=false.
sleep 1
claim_wifi_devices
adopt_current_ssid_if_needed
claim_wifi_devices

echo "NetworkManager gestiona las interfaces (ifupdown managed=true)."
