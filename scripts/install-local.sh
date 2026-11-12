#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
VENV_DIR="${AIDYCOS_VENV:-${DATA_HOME}/aidycos/venv}"
BIN_DIR="${AIDYCOS_BIN_DIR:-${HOME}/.local/bin}"
COMMAND_PATH="${BIN_DIR}/aidycos"
INSTALLED_COMMAND="${VENV_DIR}/bin/aidycos"

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  echo "No se encontró ${PYTHON}. Instala Python 3.11 o posterior." >&2
  exit 127
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]] || ! "${VENV_DIR}/bin/python" -m pip --version >/dev/null 2>&1; then
  mkdir -p "$(dirname "${VENV_DIR}")"
  if ! "${PYTHON}" -m venv --clear "${VENV_DIR}"; then
    echo "No se pudo crear un entorno virtual funcional. En Debian revisa las fuentes APT y luego instala python3-venv." >&2
    exit 1
  fi
fi

"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check "${ROOT}"
mkdir -p "${BIN_DIR}"

if [[ -e "${COMMAND_PATH}" || -L "${COMMAND_PATH}" ]]; then
  if [[ "$(readlink -f "${COMMAND_PATH}" 2>/dev/null || true)" != "$(readlink -f "${INSTALLED_COMMAND}")" ]]; then
    echo "${COMMAND_PATH} ya existe y no pertenece a esta instalación; no se modificó." >&2
    exit 1
  fi
else
  ln -s "${INSTALLED_COMMAND}" "${COMMAND_PATH}"
fi

echo "AidyCOS quedó instalado en ${VENV_DIR}."

install -m 0755 "${ROOT}/scripts/aidycos-update" "${BIN_DIR}/aidycos-update"
install -m 0755 "${ROOT}/scripts/uninstall-debian-profile.sh" "${BIN_DIR}/aidycos-uninstall"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-update.desktop" \
  "${DATA_HOME}/applications/aidycos-update.desktop"
install -D -m 0644 "${ROOT}/packaging/applications/aidycos-uninstall.desktop" \
  "${DATA_HOME}/applications/aidycos-uninstall.desktop"
install -D -m 0644 "${ROOT}/packaging/systemd/aidycos-update-check.service" \
  "${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user/aidycos-update-check.service"
install -D -m 0644 "${ROOT}/packaging/systemd/aidycos-update-check.timer" \
  "${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user/aidycos-update-check.timer"
if commit="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null)"; then
  install -d "${DATA_HOME}/aidycos"
  printf '%s\n' "${commit}" >"${DATA_HOME}/aidycos/github-commit"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DATA_HOME}/applications" >/dev/null 2>&1 || true
fi
systemctl --user daemon-reload >/dev/null 2>&1 || true

if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  echo "Agrega ${BIN_DIR} a PATH o ejecuta: ${COMMAND_PATH} doctor"
else
  echo "Prueba con: aidycos doctor"
fi
echo "El comprobador diario avisará si hay una revisión nueva en GitHub; también puedes usar el menú Actualizar AidyCOS o el atajo Super+Shift+U."
