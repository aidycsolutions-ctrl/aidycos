#!/usr/bin/env bash
# Configure a quiet graphical boot: GRUB logo + Plymouth AidyCOS splash.
# Safe to re-run. Uses absolute paths so it works when /usr/sbin is not in PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLYMOUTH_THEME_DIR=/usr/share/plymouth/themes/aidycos
GRUB_DROPIN=/etc/default/grub.d/zz-aidycos.cfg
LEGACY_AIDYC_DROPIN=/etc/default/grub.d/aidyc.cfg
CMDLINE_OPTIONS=(
  quiet
  splash
  loglevel=3
  systemd.show_status=false
  rd.systemd.show_status=false
  vt.global_cursor_default=0
  udev.log_level=3
  rd.udev.log_level=3
)

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
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

UPDATE_GRUB="$(find_sbin update-grub || true)"
UPDATE_INITRAMFS="$(find_sbin update-initramfs || true)"
PLYMOUTH_SET_THEME="$(find_sbin plymouth-set-default-theme || true)"

if [[ ! -f /etc/default/grub ]] || [[ -z "${UPDATE_GRUB}" ]]; then
  echo "GRUB no está instalado; se omite el perfil de arranque gráfico."
  exit 0
fi

if [[ ! -f "${ROOT}/packaging/boot/aidycos-boot-gfxmode" ]]; then
  echo "Falta packaging/boot/aidycos-boot-gfxmode en ${ROOT}" >&2
  exit 1
fi

run_root apt-get install -y --no-install-recommends plymouth plymouth-themes python3-pil >/dev/null
run_root install -d -m 0755 "${PLYMOUTH_THEME_DIR}"
run_root install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" "${PLYMOUTH_THEME_DIR}/AidyCOS.png"
run_root install -m 0644 "${ROOT}/packaging/plymouth/aidycos.plymouth" "${PLYMOUTH_THEME_DIR}/aidycos.plymouth"
run_root install -m 0644 "${ROOT}/packaging/plymouth/aidycos.script" "${PLYMOUTH_THEME_DIR}/aidycos.script"
run_root install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" /usr/share/backgrounds/aidycos.png
run_root install -D -m 0755 "${ROOT}/packaging/boot/aidycos-boot-gfxmode" /usr/local/bin/aidycos-boot-gfxmode
run_root install -D -m 0755 "${ROOT}/packaging/boot/aidycos-grub-background" /usr/local/bin/aidycos-grub-background

# Prefer Theme= in plymouthd.conf (Debian 13) and keep a default.plymouth link.
run_root install -d -m 0755 /etc/plymouth
run_root tee /etc/plymouth/plymouthd.conf >/dev/null <<'EOF'
# Managed by AidyCOS. Quiet boot splash with the AidyCOS logo.
[Daemon]
Theme=aidycos
ShowDelay=0
DeviceTimeout=8
EOF
if [[ -n "${PLYMOUTH_SET_THEME}" ]]; then
  run_root "${PLYMOUTH_SET_THEME}" aidycos || true
fi
run_root ln -sfn "${PLYMOUTH_THEME_DIR}/aidycos.plymouth" \
  /usr/share/plymouth/themes/default.plymouth

# Include framebuffer helpers early so Plymouth can paint before text appears.
run_root install -d -m 0755 /etc/initramfs-tools/conf.d
run_root tee /etc/initramfs-tools/conf.d/aidycos-framebuffer >/dev/null <<'EOF'
# Managed by AidyCOS.
FRAMEBUFFER=y
EOF

gfxmode="$(python3 "${ROOT}/packaging/boot/aidycos-boot-gfxmode" 2>/dev/null || true)"
if [[ -z "${gfxmode}" ]]; then
  gfxmode="1920x1080x32,1680x1050x32,1600x900x32,1366x768x32,1280x720x32,1024x768x32,auto"
fi
cmdline="${CMDLINE_OPTIONS[*]}"

echo "GRUB_GFXMODE preferido: ${gfxmode}"

# GRUB stretches backgrounds to the panel. Pre-letterbox the square logo onto a
# black canvas at the preferred mode so the mark keeps its proportions.
grub_bg_tmp="$(mktemp --suffix=.png)"
if python3 "${ROOT}/packaging/boot/aidycos-grub-background" \
     --logo "${ROOT}/packaging/plymouth/AidyCOS.png" \
     --gfxmode "${gfxmode}" \
     --output "${grub_bg_tmp}"; then
  run_root install -D -m 0644 "${grub_bg_tmp}" /boot/grub/AidyCOS.png
  echo "Fondo GRUB generado sin estirar el logo."
else
  echo "No se pudo generar el fondo letterbox; se usa el logo cuadrado." >&2
  run_root install -D -m 0644 "${ROOT}/packaging/plymouth/AidyCOS.png" /boot/grub/AidyCOS.png
fi
rm -f "${grub_bg_tmp}"

# Drop-in wins over /etc/default/grub and over leftover AidyC drop-ins.
run_root install -d -m 0755 /etc/default/grub.d
tmp_dropin="$(mktemp)"
cat >"${tmp_dropin}" <<EOF
# Managed by AidyCOS. Quiet graphical boot with logo; hides GRUB menu text.
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_DISTRIBUTOR="AidyCOS"
GRUB_BACKGROUND="/boot/grub/AidyCOS.png"
GRUB_GFXMODE="${gfxmode}"
GRUB_GFXPAYLOAD_LINUX=keep
GRUB_TERMINAL_OUTPUT=gfxterm
GRUB_CMDLINE_LINUX_DEFAULT="${cmdline}"
EOF
run_root install -m 0644 "${tmp_dropin}" "${GRUB_DROPIN}"
rm -f "${tmp_dropin}"

if [[ -f "${LEGACY_AIDYC_DROPIN}" ]]; then
  run_root cp -a "${LEGACY_AIDYC_DROPIN}" \
    "${LEGACY_AIDYC_DROPIN}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  run_root mv -f "${LEGACY_AIDYC_DROPIN}" "${LEGACY_AIDYC_DROPIN}.disabled"
  echo "Se desactivó el drop-in legado ${LEGACY_AIDYC_DROPIN}."
fi

# Keep /etc/default/grub aligned so tools that ignore drop-ins still look quiet.
run_root python3 - <<PY
from pathlib import Path
import re

path = Path("/etc/default/grub")
text = path.read_text(encoding="utf-8")
backup = path.with_name(path.name + ".aidycos-backup")
if not backup.exists():
    backup.write_text(text, encoding="utf-8")

replacements = {
    "GRUB_TIMEOUT": "0",
    "GRUB_TIMEOUT_STYLE": "hidden",
    "GRUB_BACKGROUND": '"/boot/grub/AidyCOS.png"',
    "GRUB_GFXMODE": '"${gfxmode}"',
    "GRUB_GFXPAYLOAD_LINUX": "keep",
    "GRUB_TERMINAL_OUTPUT": "gfxterm",
    "GRUB_CMDLINE_LINUX_DEFAULT": '"${cmdline}"',
}
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    matched_key = None
    for key in replacements:
        if re.match(rf"^#?{key}=", line):
            matched_key = key
            break
    if matched_key is None:
        out.append(line)
        continue
    if matched_key in seen:
        continue
    out.append(f"{matched_key}={replacements[matched_key]}")
    seen.add(matched_key)
for key, value in replacements.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

linux_generator=/etc/grub.d/10_linux
if [[ -f "${linux_generator}" ]] && run_root grep -q '^quiet_boot="0"$' "${linux_generator}"; then
  run_root cp -a "${linux_generator}" "${linux_generator}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
  run_root sed -i 's/^quiet_boot="0"$/quiet_boot="1"/' "${linux_generator}"
fi

run_root "${UPDATE_GRUB}"
if [[ -n "${UPDATE_INITRAMFS}" ]]; then
  run_root "${UPDATE_INITRAMFS}" -u -k all
fi

echo "Arranque gráfico AidyCOS aplicado (GRUB oculto + Plymouth con logo)."
