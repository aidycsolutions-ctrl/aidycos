#!/usr/bin/env bash
# Reclaim Wi-Fi for NetworkManager after boot when Debian ifupdown left the
# adapter stuck (unavailable / empty scan) until a manual iface bounce.
# Idempotent: healthy systems (connected, or disconnected with APs visible)
# exit quietly without bouncing.
set -euo pipefail

log() {
  logger -t aidycos-wifi-reclaim -- "$@" 2>/dev/null || true
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

wait_for_network_manager() {
  local i
  for i in $(seq 1 60); do
    if systemctl is-active --quiet NetworkManager.service 2>/dev/null; then
      if command -v nmcli >/dev/null 2>&1 && nmcli -t general status >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

enable_wifi_radio() {
  if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock wifi >/dev/null 2>&1 || true
    rfkill unblock wlan >/dev/null 2>&1 || true
  fi
  nmcli radio wifi on >/dev/null 2>&1 || true
}

claim_wifi_devices() {
  local device state
  while IFS=: read -r device _type state _; do
    [[ -n "${device}" ]] || continue
    case "${state}" in
      unmanaged|unavailable)
        nmcli device set "${device}" managed yes >/dev/null 2>&1 || true
        log "claimed ${device} (was ${state})"
        ;;
    esac
  done < <(nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '$2=="wifi"{print}')
}

ensure_wifi_autoconnect() {
  local uuid type
  while IFS=: read -r _name uuid type; do
    [[ "${type}" == "802-11-wireless" ]] || continue
    [[ -n "${uuid}" ]] || continue
    nmcli connection modify uuid "${uuid}" connection.autoconnect yes >/dev/null 2>&1 || true
  done < <(nmcli -t -f NAME,UUID,TYPE connection show 2>/dev/null)
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
}

# Stop ifupdown-style wpa_supplicant only. Do not touch the D-Bus daemon
# NetworkManager starts (typically wpa_supplicant -u ...).
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
            log "stopping orphan wpa_supplicant pid=${pid}"
            run_root kill "${pid}" >/dev/null 2>&1 || true
            ;;
        esac
        ;;
    esac
  done < <(pgrep -x wpa_supplicant 2>/dev/null || true)
}

bounce_wifi_iface() {
  local device="$1"
  [[ -n "${device}" ]] || return 0
  log "bouncing ${device} and restarting NetworkManager"
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

wifi_needs_reclaim_bounce() {
  local state count
  state="$(primary_wifi_state)"
  case "${state}" in
    unmanaged|unavailable|"")
      return 0
      ;;
    connected|connecting|disconnecting|deactivating|need-auth)
      return 1
      ;;
  esac
  # disconnected / failed / unknown: bounce only when scan sees nothing
  force_wifi_rescan
  count="$(wifi_ap_count)"
  [[ "${count:-0}" -eq 0 ]]
}

main() {
  command -v nmcli >/dev/null 2>&1 || exit 0
  wait_for_network_manager || exit 0

  enable_wifi_radio
  claim_wifi_devices
  ensure_wifi_autoconnect

  local device state
  device="$(primary_wifi_device)"
  [[ -n "${device}" ]] || exit 0

  state="$(primary_wifi_state)"
  case "${state}" in
    connected|connecting)
      exit 0
      ;;
  esac

  # Healthy: disconnected (or similar) with APs already visible — no bounce.
  if [[ "${state}" == "disconnected" ]] || [[ "${state}" == "failed" ]]; then
    force_wifi_rescan
    if [[ "$(wifi_ap_count)" -gt 0 ]]; then
      exit 0
    fi
  fi

  if wifi_needs_reclaim_bounce; then
    # Re-read device in case naming changed; bounce at most once.
    device="$(primary_wifi_device)"
    bounce_wifi_iface "${device}"
    ensure_wifi_autoconnect
    claim_wifi_devices
  fi
}

main "$@"
