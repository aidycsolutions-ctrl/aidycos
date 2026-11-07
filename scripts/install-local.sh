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
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  echo "Agrega ${BIN_DIR} a PATH o ejecuta: ${COMMAND_PATH} doctor"
else
  echo "Prueba con: aidycos doctor"
fi
