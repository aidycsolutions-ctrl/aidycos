#!/usr/bin/env bash
# Build the csd-minimize plugin so Cursor/Chrome/Electron CSD minimize buttons
# call ventanas (Hyprland otherwise ignores those buttons).
#
# Shares hyprland-dev / compat-headers with setup-hyprbars.sh.
#
#   bash packaging/hyprland/setup-csd-minimize.sh
#   CSD_MINIMIZE_FORCE=1 bash packaging/hyprland/setup-csd-minimize.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGING="$ROOT/packaging/hyprland"
SRC="$PACKAGING/csd-minimize-src"
COMPAT_ROOT="$PACKAGING/compat-headers"
HYPR_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
PLUGIN_DIR="$HOME/.local/lib/jugoo"
PLUGIN="$PLUGIN_DIR/csd-minimize.so"
STAMP="$PLUGIN_DIR/csd-minimize.hyprland-version"
CONF="$HYPR_HOME/config/jugoo_csd_minimize.conf"
SOURCE_LINE='source = ~/.config/hypr/config/jugoo_csd_minimize.conf'
PACKAGES=(hyprland-dev pkgconf libpixman-1-dev libudev-dev g++)
BUILD_LOG=""

die() {
    echo "error: $*" >&2
    exit 1
}

backup_file() {
    local path=$1
    [[ -e "$path" ]] || return 0
    cp -a "$path" "${path}.aidycos-backup-$(date +%Y%m%d%H%M%S)"
}

[[ -f "$SRC/main.cpp" ]] || die "faltan fuentes vendored en ${SRC}"
[[ -f "$PACKAGING/jugoo_csd_minimize.conf.in" ]] || die "falta jugoo_csd_minimize.conf.in"

running="$(dpkg-query -W -f='${Version}' hyprland 2>/dev/null || true)"
[[ -n "$running" ]] || die "hyprland no está instalado"

write_conf() {
    mkdir -p "$(dirname "$CONF")"
    local expected
    expected="$(sed -e "s|@PLUGIN@|$PLUGIN|g" -e "s|@VENTANAS@|$HYPR_HOME/scripts/ventanas|g" \
        "$PACKAGING/jugoo_csd_minimize.conf.in")"
    if [[ -e "$CONF" && "$(cat "$CONF")" != "$expected" ]]; then
        backup_file "$CONF"
    fi
    printf '%s\n' "$expected" >"$CONF"
}

ensure_source() {
    local aidycos="$HYPR_HOME/aidycos.conf"
    local hypr="$HYPR_HOME/hyprland.conf"
    mkdir -p "$HYPR_HOME"
    if [[ -f "$aidycos" ]] && grep -qF "$SOURCE_LINE" "$aidycos"; then
        return 0
    fi
    if [[ -f "$hypr" ]] && grep -qF "$SOURCE_LINE" "$hypr"; then
        return 0
    fi
    if [[ -f "$aidycos" ]]; then
        backup_file "$aidycos"
        printf '\n%s\n' "$SOURCE_LINE" >>"$aidycos"
        echo "  → source añadido en $aidycos"
        return 0
    fi
    if [[ -f "$hypr" ]]; then
        backup_file "$hypr"
        printf '\n%s\n' "$SOURCE_LINE" >>"$hypr"
        echo "  → source añadido en $hypr"
        return 0
    fi
    printf '%s\n' "$SOURCE_LINE" >"$aidycos"
    echo "  → creado $aidycos con source de csd-minimize"
}

plugin_loaded() {
    [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || return 1
    command -v hyprctl >/dev/null 2>&1 || return 1
    hyprctl plugin list 2>/dev/null | grep -qi '^Plugin csd-minimize'
}

reload_and_check() {
    if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || ! command -v hyprctl >/dev/null 2>&1; then
        return 0
    fi
    # Unload first so a rebuilt .so actually replaces the in-memory plugin.
    hyprctl plugin unload "$PLUGIN" >/dev/null 2>&1 || true
    hyprctl plugin load "$PLUGIN" >/dev/null 2>&1 || true
    hyprctl reload >/dev/null 2>&1 || true
    sleep 1
    if plugin_loaded; then
        echo "  → plugin csd-minimize cargado en la sesión"
        hyprctl plugin list 2>/dev/null | grep -i csd-minimize || true
        return 0
    fi
    echo "aviso: csd-minimize.so instalado pero Hyprland no lo cargó" >&2
    hyprctl plugin list 2>/dev/null || true
    return 1
}

find_version_h() {
    local cand
    for cand in \
        /usr/include/x86_64-linux-gnu/hyprland/src/version.h \
        /usr/include/hyprland/src/version.h \
        /usr/include/*/hyprland/src/version.h; do
        if [[ -f "$cand" ]]; then
            printf '%s\n' "$cand"
            return 0
        fi
    done
    return 1
}

hyprland_built_hyprutils() {
    local version_h=$1
    sed -n 's/^#define[[:space:]]\+HYPRUTILS_VERSION[[:space:]]\+"\([^"]*\)".*/\1/p' "$version_h" | head -1
}

compat_hyprutils_dir() {
    local want=$1
    local dir="$COMPAT_ROOT/hyprutils-${want}"
    if [[ -d "$dir/hyprutils/memory" ]]; then
        printf '%s\n' "$dir"
        return 0
    fi
    return 1
}

hyprutils_has_explicit_bool() {
    local includedir header=""
    includedir="$(pkg-config --variable=includedir hyprutils 2>/dev/null || true)"
    if [[ -n "$includedir" && -f "$includedir/hyprutils/memory/SharedPtr.hpp" ]]; then
        header="$includedir/hyprutils/memory/SharedPtr.hpp"
    elif [[ -f /usr/include/hyprutils/memory/SharedPtr.hpp ]]; then
        header=/usr/include/hyprutils/memory/SharedPtr.hpp
    else
        return 1
    fi
    grep -qE '[[:space:]]explicit[[:space:]]+operator[[:space:]]+bool[[:space:]]*\(' "$header"
}

needs_build=0
if [[ "${CSD_MINIMIZE_FORCE:-0}" == "1" || "${HYPRBARS_FORCE:-0}" == "1" ]]; then
    needs_build=1
    echo "• force → recompilar csd-minimize"
elif [[ ! -f "$PLUGIN" ]]; then
    needs_build=1
elif [[ -f "$STAMP" && "$(cat "$STAMP")" == "$running" ]]; then
    write_conf
    ensure_source
    echo "• csd-minimize ya compilado para hyprland ${running}"
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
        if reload_and_check; then
            exit 0
        fi
        needs_build=1
    else
        exit 0
    fi
else
    needs_build=1
fi

missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
    echo "• instalando dependencias: ${missing[*]}"
    if ! sudo apt-get install -y --no-install-recommends -t trixie-backports "${missing[@]}" \
        && ! sudo apt-get install -y --no-install-recommends "${missing[@]}"; then
        die "no se pudieron instalar dependencias: ${missing[*]}"
    fi
fi

version_h="$(find_version_h)" || die "no se encontró hyprland/src/version.h (¿hyprland-dev?)"
built_hu="$(hyprland_built_hyprutils "$version_h")"
sys_hu="$(pkg-config --modversion hyprutils 2>/dev/null || true)"
compat_inc=()
use_compat_hu=0
if [[ -n "$built_hu" ]]; then
    if [[ -z "$sys_hu" ]]; then
        use_compat_hu=1
    elif [[ "$sys_hu" != "$built_hu" ]]; then
        use_compat_hu=1
    elif hyprutils_has_explicit_bool; then
        use_compat_hu=1
    fi
fi
if ((use_compat_hu)); then
    compat_dir="$(compat_hyprutils_dir "$built_hu")" || die "faltan headers compatibles hyprutils ${built_hu}"
    compat_inc+=("-I$compat_dir")
    echo "  → headers hyprutils ${built_hu}: $compat_dir"
fi

work="$(mktemp -d)"
BUILD_LOG="$work/build.log"
trap 'rm -rf "$work"' EXIT
cp -a "$SRC/." "$work/csd/"
cd "$work/csd"

echo "• compilando csd-minimize"
# shellcheck disable=SC2046
if ! g++ -shared -fPIC -O2 -std=c++2b --no-gnu-unique \
    "${compat_inc[@]}" \
    $(pkg-config --cflags pixman-1 libdrm hyprland libinput libudev wayland-server xkbcommon) \
    main.cpp -o csd-minimize.so \
    >"$BUILD_LOG" 2>&1; then
    echo "error: falló la compilación de csd-minimize" >&2
    tail -n 40 "$BUILD_LOG" >&2 || true
    rm -f "$STAMP"
    exit 1
fi

install -Dm644 csd-minimize.so "$PLUGIN"
printf '%s\n' "$running" >"$STAMP"
write_conf
ensure_source
echo "  → $PLUGIN"
echo "  → $CONF"

if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    if ! reload_and_check; then
        die "el .so se generó pero Hyprland no cargó csd-minimize"
    fi
else
    reload_and_check || true
fi
echo "Listo: minimizar/maximizar CSD (Cursor, Chrome, …) → ventanas."
