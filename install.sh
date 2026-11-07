#!/usr/bin/env bash
# One-line remote bootstrap: curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/aidycsolutions-ctrl/aidycos"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aidycos.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

command -v curl >/dev/null || { echo "Falta curl. Instálalo y vuelve a ejecutar." >&2; exit 127; }
command -v tar >/dev/null || { echo "Falta tar. Instálalo y vuelve a ejecutar." >&2; exit 127; }

curl -fL --retry 3 "${REPO}/archive/refs/heads/main.tar.gz" -o "${TMP_DIR}/aidycos.tar.gz"
tar -xzf "${TMP_DIR}/aidycos.tar.gz" --strip-components=1 -C "${TMP_DIR}"
bash "${TMP_DIR}/scripts/install-debian-profile.sh" "$@"
