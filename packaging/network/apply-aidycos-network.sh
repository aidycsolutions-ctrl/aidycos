#!/usr/bin/env bash
# Give NetworkManager ownership of Wi-Fi left on Debian ifupdown after install.
# Jugoo only talks to NetworkManager; unmanaged/unavailable wifi cannot scan.
#
# Conflict policy: NetworkManager is the sole manager. We disable/mask
# networking.service (ifupdown) and wpa_supplicant@.service (per-iface
# template). We never mask/disable the D-Bus wpa_supplicant.service that NM uses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NM_CONF_D=/etc/NetworkManager/conf.d
NM_MANAGED_DROPIN="${NM_CONF_D}/99-aidycos-ifupdown.conf"
NM_WIFI_DROPIN="${NM_CONF_D}/99-aidycos-wifi.conf"
INTERFACES=/etc/network/interfaces
INTERFACES_D=/etc/network/interfaces.d
NM_CONNECTIONS=/etc/NetworkManager/system-connections
MARKER=/var/lib/aidycos/network-migrated
WPA_SUPPLICANT_CONF=/etc/wpa_supplicant/wpa_supplicant.conf
RECLAIM_SRC="${SCRIPT_DIR}/aidycos-wifi-reclaim.sh"
RECLAIM_UNIT_SRC="${SCRIPT_DIR}/aidycos-wifi-reclaim.service"
RECLAIM_DST=/usr/local/libexec/aidycos/aidycos-wifi-reclaim.sh
RECLAIM_UNIT_DST=/etc/systemd/system/aidycos-wifi-reclaim.service

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

interfaces_still_claim_wifi() {
  has_non_loopback_iface_config "${INTERFACES}" && return 0
  if [[ -d "${INTERFACES_D}" ]]; then
    local dropin
    shopt -s nullglob
    for dropin in "${INTERFACES_D}"/*; do
      [[ -f "${dropin}" ]] || continue
      [[ "$(basename "${dropin}")" == *aidycos-backup* ]] && continue
      if has_non_loopback_iface_config "${dropin}"; then
        shopt -u nullglob
        return 0
      fi
    done
    shopt -u nullglob
  fi
  return 1
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
  # Never create a blank/PSK-less profile: that looks secured but cannot
  # authenticate, and we cannot safely assume the AP is open.
  if [[ -z "${psk}" ]]; then
    return 0
  fi

  run_root install -d -m 0755 "${NM_CONNECTIONS}"
  safe="$(printf '%s' "${ssid}" | tr -c 'A-Za-z0-9._-' '_')"
  dest="${NM_CONNECTIONS}/aidycos-${safe}.nmconnection"
  if run_root test -e "${dest}"; then
    return 0
  fi
  if command -v nmcli >/dev/null 2>&1; then
    if nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep -Fxq "${ssid}:802-11-wireless"; then
      return 0
    fi
  fi

  uuid="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')"
  {
    printf '[connection]\nid=%s\nuuid=%s\ntype=wifi\nautoconnect=true\n\n' "${ssid}" "${uuid}"
    printf '[wifi]\nmode=infrastructure\nssid=%s\n\n' "${ssid}"
    printf '[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n\n' "${psk}"
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

migrate_ifupdown_wifi() {
  backup_and_loopback_only "${INTERFACES}"
  if [[ -d "${INTERFACES_D}" ]]; then
    local dropin
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
}

claim_wifi_devices() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local device state
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

wait_for_wifi_ready() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local i device state
  for i in $(seq 1 20); do
    claim_wifi_devices
    state="$(nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '$2=="wifi"{print $3; exit}')"
    case "${state}" in
      connected|disconnected|connecting|disconnecting|deactivating|failed|need-auth)
        echo "Adaptador Wi-Fi listo (estado ${state})."
        return 0
        ;;
    esac
    sleep 0.5
  done
  echo "Aviso: el adaptador Wi-Fi sigue en estado «${state:-desconocido}» tras esperar a NetworkManager."
  return 0
}

enable_wifi_radio() {
  if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock wifi >/dev/null 2>&1 || true
    rfkill unblock wlan >/dev/null 2>&1 || true
  fi
  if command -v nmcli >/dev/null 2>&1; then
    nmcli radio wifi on >/dev/null 2>&1 || true
  fi
}

primary_wifi_device() {
  nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}'
}

primary_wifi_state() {
  nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '$2=="wifi"{print $3; exit}'
}

wifi_ap_count() {
  nmcli -t -f SSID device wifi list 2>/dev/null | awk 'NF' | wc -l | tr -d ' '
}

force_wifi_rescan() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local device
  device="$(primary_wifi_device)"
  if [[ -n "${device}" ]]; then
    nmcli device wifi rescan ifname "${device}" >/dev/null 2>&1 \
      || nmcli device wifi rescan >/dev/null 2>&1 \
      || true
  else
    nmcli device wifi rescan >/dev/null 2>&1 || true
  fi
  sleep 2
  local count
  count="$(wifi_ap_count)"
  echo "Escaneo Wi-Fi: ${count:-0} redes visibles para NetworkManager."
}

# Stop ifupdown-style wpa_supplicant only — never the D-Bus (-u) daemon NM owns.
stop_orphan_wpa_supplicant() {
  local pid cmd
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    cmd="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    case "${cmd}" in
      *wpa_supplicant*)
        case "${cmd}" in
          *' -u '*|*'/wpa_supplicant -u'*|*-u\ -s*|*-u\ -O*)
            continue
            ;;
          *'/etc/wpa_supplicant'*|*' -iwlp'*|*' -iwlan'*|*' -iwlx'*|*' -i wlp'*|*' -i wlan'*|*' -i wlx'*)
            echo "Deteniendo wpa_supplicant huérfano (pid ${pid})."
            run_root kill "${pid}" >/dev/null 2>&1 || true
            ;;
        esac
        ;;
    esac
  done < <(pgrep -x wpa_supplicant 2>/dev/null || true)
}

reclaim_bounce_wifi_once() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local device state count
  device="$(primary_wifi_device)"
  [[ -n "${device}" ]] || return 0
  state="$(primary_wifi_state)"
  count="$(wifi_ap_count)"

  case "${state}" in
    unmanaged|unavailable)
      ;;
    *)
      if [[ "${count:-0}" -gt 0 ]]; then
        return 0
      fi
      # Empty scan: try one controlled bounce (same idea as the manual workaround).
      ;;
  esac

  echo "Recuperando ${device} (estado ${state:-desconocido}, APs ${count:-0})…"
  stop_orphan_wpa_supplicant
  run_root ip link set "${device}" down >/dev/null 2>&1 || true
  sleep 1
  run_root ip link set "${device}" up >/dev/null 2>&1 || true
  run_root systemctl restart NetworkManager.service >/dev/null 2>&1 || true
  sleep 3
  enable_wifi_radio
  claim_wifi_devices
  force_wifi_rescan
}

ensure_wifi_autoconnect() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local uuid type
  while IFS=: read -r _name uuid type; do
    [[ "${type}" == "802-11-wireless" ]] || continue
    [[ -n "${uuid}" ]] || continue
    # Modify by UUID; never dump secrets.
    nmcli connection modify uuid "${uuid}" connection.autoconnect yes >/dev/null 2>&1 || true
  done < <(nmcli -t -f NAME,UUID,TYPE connection show 2>/dev/null)
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
  # Only bring up an existing profile — never invent a blank PSK connection.
  if nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep -Fxq "${ssid}:802-11-wireless"; then
    nmcli connection up id "${ssid}" >/dev/null 2>&1 || true
  fi
}

disable_ifupdown_conflicts() {
  # NM is sole manager: stop ifupdown networking and mask so it cannot reclaim
  # the iface on later boots.
  if systemctl list-unit-files networking.service >/dev/null 2>&1; then
    run_root systemctl disable --now networking.service >/dev/null 2>&1 || true
    run_root systemctl mask networking.service >/dev/null 2>&1 || true
  fi

  # Per-interface template only. Do NOT touch wpa_supplicant.service (D-Bus).
  if systemctl list-unit-files 'wpa_supplicant@.service' >/dev/null 2>&1; then
    run_root systemctl disable --now 'wpa_supplicant@*.service' >/dev/null 2>&1 || true
    run_root systemctl mask 'wpa_supplicant@.service' >/dev/null 2>&1 || true
  fi
}

install_wifi_reclaim_oneshot() {
  [[ -f "${RECLAIM_SRC}" ]] || return 0
  [[ -f "${RECLAIM_UNIT_SRC}" ]] || return 0
  run_root install -d -m 0755 /usr/local/libexec/aidycos
  run_root install -D -m 0755 "${RECLAIM_SRC}" "${RECLAIM_DST}"
  run_root install -D -m 0644 "${RECLAIM_UNIT_SRC}" "${RECLAIM_UNIT_DST}"
  run_root systemctl daemon-reload >/dev/null 2>&1 || true
  # enable for later boots; restart so RemainAfterExit oneshot re-runs on re-apply
  run_root systemctl enable aidycos-wifi-reclaim.service >/dev/null 2>&1 || true
  run_root systemctl restart aidycos-wifi-reclaim.service >/dev/null 2>&1 || true
}

run_root install -d -m 0755 "${NM_CONF_D}" /var/lib/aidycos
printf '%s\n' \
  '[main]' \
  'plugins=ifupdown,keyfile' \
  '' \
  '[ifupdown]' \
  'managed=true' \
  | run_root tee "${NM_MANAGED_DROPIN}" >/dev/null

# Minimal Wi-Fi defaults: disable scan MAC randomization (helps flaky Realtek/
# Broadcom on Debian). Keep NM as DHCP/Wi-Fi owner — no competing clients.
printf '%s\n' \
  '# AidyCOS Wi-Fi defaults (NetworkManager sole manager; avoid DHCP/ifupdown fights).' \
  '[device]' \
  'wifi.scan-rand-mac-address=no' \
  | run_root tee "${NM_WIFI_DROPIN}" >/dev/null

if run_root test -f /etc/NetworkManager/NetworkManager.conf; then
  if run_root grep -q '^[[:space:]]*managed[[:space:]]*=' /etc/NetworkManager/NetworkManager.conf; then
    run_root sed -i 's/^[[:space:]]*managed[[:space:]]*=.*/managed=true/' /etc/NetworkManager/NetworkManager.conf
  fi
fi

if [[ ! -e "${MARKER}" ]] || interfaces_still_claim_wifi; then
  migrate_ifupdown_wifi
  run_root install -D -m 0644 /dev/null "${MARKER}"
fi

disable_ifupdown_conflicts

run_root systemctl enable NetworkManager.service >/dev/null 2>&1 || true
run_root systemctl restart NetworkManager.service >/dev/null 2>&1 || true

sleep 1
enable_wifi_radio
wait_for_wifi_ready
ensure_wifi_autoconnect
adopt_current_ssid_if_needed
force_wifi_rescan
claim_wifi_devices
reclaim_bounce_wifi_once
ensure_wifi_autoconnect

install_wifi_reclaim_oneshot

echo "NetworkManager gestiona las interfaces (ifupdown managed=true) y el Wi-Fi puede escanear."
