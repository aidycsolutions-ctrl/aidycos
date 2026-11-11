#!/usr/bin/env bash
# One-line remote bootstrap:
#   curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh | bash
#
# On a minimal Debian (no desktop, no sudo yet) you can also run it as root:
#   su -
#   curl -fsSL ... | bash
# The profile script will enable sudo for your normal user and continue as that user.
set -euo pipefail

REPO="https://github.com/aidycsolutions-ctrl/aidycos"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aidycos.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

ensure_curl() {
  if command -v curl >/dev/null; then
    return 0
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    echo "Falta curl; instalándolo…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends curl ca-certificates
    return 0
  fi
  cat <<'EOF' >&2
Falta curl.

Como root:

  su -
  apt-get update
  apt-get install -y curl ca-certificates
  exit

Luego vuelve a lanzar el instalador con tu usuario normal
(o como root; el perfil prepara sudo solo).
EOF
  exit 127
}

ensure_curl
command -v tar >/dev/null || {
  if [[ "${EUID}" -eq 0 ]]; then
    apt-get install -y --no-install-recommends tar
  else
    echo "Falta tar. Instálalo y vuelve a ejecutar." >&2
    exit 127
  fi
}

curl -fL --retry 3 "${REPO}/archive/refs/heads/main.tar.gz" -o "${TMP_DIR}/aidycos.tar.gz"
tar -xzf "${TMP_DIR}/aidycos.tar.gz" --strip-components=1 -C "${TMP_DIR}"
bash "${TMP_DIR}/scripts/install-debian-profile.sh" "$@"
