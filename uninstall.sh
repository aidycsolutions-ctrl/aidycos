#!/usr/bin/env bash
# One-line remote uninstall:
#   curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/uninstall.sh | bash
set -euo pipefail

REPO="https://github.com/aidycsolutions-ctrl/aidycos"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aidycos-uninstall.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

ensure_curl() {
  if command -v curl >/dev/null; then
    return 0
  fi
  echo "Falta curl. Instálalo y vuelve a ejecutar." >&2
  exit 127
}

ensure_curl
command -v tar >/dev/null || {
  echo "Falta tar. Instálalo y vuelve a ejecutar." >&2
  exit 127
}

curl -fL --retry 3 "${REPO}/archive/refs/heads/main.tar.gz" -o "${TMP_DIR}/aidycos.tar.gz"
tar -xzf "${TMP_DIR}/aidycos.tar.gz" --strip-components=1 -C "${TMP_DIR}"
bash "${TMP_DIR}/scripts/uninstall-debian-profile.sh" "$@"
