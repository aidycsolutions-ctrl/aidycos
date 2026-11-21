#!/usr/bin/env bash
# Build the hyprbars plugin (title bars with minimize / maximize / close) against
# the installed Hyprland. Debian's hyprland-plugin-hyprbars targets another ABI,
# so it is compiled locally from vendored hyprland-plugins sources (plus the
# drag-end patch already applied in packaging/hyprland/hyprbars-src).
#
# Debian Trixie Backports may install libhyprutils-dev newer than the version
# Hyprland was built against. In that case we compile against the matching
# vendored headers under packaging/hyprland/compat-headers/ (no GitHub fetch).
#
#   bash packaging/hyprland/setup-hyprbars.sh
#   HYPRBARS_FORCE=1 bash packaging/hyprland/setup-hyprbars.sh   # rebuild even if stamp matches
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGING="$ROOT/packaging/hyprland"
SRC="$PACKAGING/hyprbars-src"
COMPAT_ROOT="$PACKAGING/compat-headers"
HYPR_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
PLUGIN_DIR="$HOME/.local/lib/jugoo"
PLUGIN="$PLUGIN_DIR/hyprbars.so"
STAMP="$PLUGIN_DIR/hyprbars.hyprland-version"
CONF="$HYPR_HOME/config/jugoo_hyprbars.conf"
SOURCE_LINE='source = ~/.config/hypr/config/jugoo_hyprbars.conf'
PACKAGES=(hyprland-dev pkgconf libpango1.0-dev libpixman-1-dev libudev-dev g++)
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

if [[ ! -f "$PACKAGING/jugoo_hyprbars.conf.in" ]]; then
    die "falta ${PACKAGING}/jugoo_hyprbars.conf.in"
fi
for needed in main.cpp barDeco.cpp barDeco.hpp BarPassElement.cpp BarPassElement.hpp globals.hpp; do
    if [[ ! -f "$SRC/$needed" ]]; then
        die "faltan fuentes vendored de hyprbars en ${SRC}"
    fi
done

running="$(dpkg-query -W -f='${Version}' hyprland 2>/dev/null || true)"
if [[ -z "$running" ]]; then
    die "hyprland no está instalado"
fi

write_conf() {
    mkdir -p "$(dirname "$CONF")"
    if [[ -e "$CONF" ]]; then
        local expected
        expected="$(sed -e "s|@PLUGIN@|$PLUGIN|g" -e "s|@VENTANAS@|$HYPR_HOME/scripts/ventanas|g" \
            "$PACKAGING/jugoo_hyprbars.conf.in")"
        if [[ "$(cat "$CONF")" != "$expected" ]]; then
            backup_file "$CONF"
        fi
    fi
    sed -e "s|@PLUGIN@|$PLUGIN|g" -e "s|@VENTANAS@|$HYPR_HOME/scripts/ventanas|g" \
        "$PACKAGING/jugoo_hyprbars.conf.in" >"$CONF"
    CSD="$(dirname "$CONF")/jugoo_hyprbars_csd.conf"
    if [[ ! -f "$CSD" ]]; then
        printf '%s\n' "# Generado por ventanas. No editar." >"$CSD"
    fi
}

# Hyprland only loads the plugin when this line is sourced. Older failed installs
# left a .so without ever wiring hyprland.conf / aidycos.conf.
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
    echo "  → creado $aidycos con source de hyprbars"
}

plugin_loaded() {
    [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || return 1
    command -v hyprctl >/dev/null 2>&1 || return 1
    hyprctl plugin list 2>/dev/null | grep -qi '^Plugin hyprbars'
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
        echo "  → plugin hyprbars cargado en la sesión"
        hyprctl plugin list 2>/dev/null | grep -i hyprbars || true
        return 0
    fi
    echo "aviso: hyprbars.so instalado pero Hyprland no lo cargó (mira hyprctl plugin list)" >&2
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

hyprland_built_aquamarine() {
    local version_h=$1
    sed -n 's/^#define[[:space:]]\+AQUAMARINE_VERSION[[:space:]]\+"\([^"]*\)".*/\1/p' "$version_h" | head -1
}

pkg_version() {
    local mod=$1
    pkg-config --modversion "$mod" 2>/dev/null || true
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
if [[ "${HYPRBARS_FORCE:-0}" == "1" ]]; then
    needs_build=1
    echo "• HYPRBARS_FORCE=1 → recompilar hyprbars"
elif [[ ! -f "$PLUGIN" ]]; then
    needs_build=1
elif [[ -f "$STAMP" && "$(cat "$STAMP")" == "$running" ]]; then
    write_conf
    ensure_source
    echo "• hyprbars ya compilado para hyprland ${running}"
    echo "  → $PLUGIN"
    echo "  → $CONF"
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
        if reload_and_check; then
            exit 0
        fi
        echo "• recompilando porque el plugin no carga en esta sesión…"
        needs_build=1
    else
        exit 0
    fi
elif [[ -f "$PLUGIN" && ! -f "$STAMP" ]]; then
    # Legacy installs (plugin without stamp): keep the .so, record the version, refresh conf.
    printf '%s\n' "$running" >"$STAMP"
    write_conf
    ensure_source
    echo "• hyprbars existente; se registró versión ${running}"
    echo "  → $PLUGIN"
    echo "  → $CONF"
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
        reload_and_check || true
    fi
    exit 0
else
    needs_build=1
fi

missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
    echo "• instalando dependencias: ${missing[*]}"
    # hyprland-dev lives in trixie-backports with hyprland itself.
    if ! sudo apt-get install -y --no-install-recommends -t trixie-backports "${missing[@]}" \
        && ! sudo apt-get install -y --no-install-recommends "${missing[@]}"; then
        die "no se pudieron instalar dependencias: ${missing[*]}"
    fi
fi

headers="$(dpkg-query -W -f='${Version}' hyprland-dev 2>/dev/null || true)"
if [[ -z "$headers" ]]; then
    die "hyprland-dev no está instalado (necesario para compilar el plugin)"
fi
if [[ "$running" != "$headers" ]]; then
    die "hyprland ($running) y hyprland-dev ($headers) no coinciden"
fi

if ! command -v pkg-config >/dev/null 2>&1 && ! command -v pkgconf >/dev/null 2>&1; then
    die "pkg-config/pkgconf no está disponible"
fi

version_h="$(find_version_h)" || die "no se encontró version.h de hyprland-dev"
built_hu="$(hyprland_built_hyprutils "$version_h")"
built_aq="$(hyprland_built_aquamarine "$version_h")"
sys_hu="$(pkg_version hyprutils)"
sys_aq="$(pkg_version aquamarine)"

echo "• Hyprland ${running} (built against hyprutils ${built_hu:-?}, aquamarine ${built_aq:-?})"
echo "  → hyprland-dev ${headers}"
echo "  → pkg-config hyprutils ${sys_hu:-ausente}, aquamarine ${sys_aq:-ausente}"

compat_inc=()
use_compat_hu=0
if [[ -n "$built_hu" ]]; then
    if [[ -z "$sys_hu" ]]; then
        use_compat_hu=1
        echo "aviso: libhyprutils-dev no aporta pkg-config; se usarán headers compatibles vendored" >&2
    elif [[ "$sys_hu" != "$built_hu" ]]; then
        use_compat_hu=1
        echo "aviso: libhyprutils-dev ${sys_hu} != built-against ${built_hu}; usando headers compatibles vendored" >&2
    elif hyprutils_has_explicit_bool; then
        # Same version string but still broken (should not happen); be safe.
        use_compat_hu=1
        echo "aviso: hyprutils del sistema tiene operator bool explícito; usando headers compatibles vendored" >&2
    fi
fi

if ((use_compat_hu)); then
    if [[ -z "$built_hu" ]]; then
        die "no se pudo leer HYPRUTILS_VERSION desde ${version_h}"
    fi
    compat_dir="$(compat_hyprutils_dir "$built_hu")" || {
        echo "error: faltan headers compatibles para hyprutils ${built_hu}" >&2
        echo "  Esperado: ${COMPAT_ROOT}/hyprutils-${built_hu}/hyprutils/" >&2
        echo "  Causa típica: apt instala libhyprutils-dev más nuevo que el de Hyprland ${running}." >&2
        exit 1
    }
    # Must come before pkg-config -I/usr/include so #include <hyprutils/...>
    # resolves to the Hyprland-built-against API, not a newer system -dev.
    compat_inc+=("-I$compat_dir")
    echo "  → headers hyprutils ${built_hu}: $compat_dir"
fi

work="$(mktemp -d)"
BUILD_LOG="$work/build.log"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/hyprbars"
cp -a "$SRC/." "$work/hyprbars/"

echo "• compilando hyprbars (fuentes locales, sin GitHub)"
cd "$work/hyprbars"

# Do not pass clang-only warning flags; g++ on Debian 13 rejects them.
# shellcheck disable=SC2046
if ! g++ -shared -fPIC -O2 -std=c++2b --no-gnu-unique \
    "${compat_inc[@]}" \
    $(pkg-config --cflags pixman-1 libdrm hyprland libinput libudev wayland-server xkbcommon pangocairo lua5.4) \
    main.cpp barDeco.cpp BarPassElement.cpp -o hyprbars.so \
    >"$BUILD_LOG" 2>&1; then
    echo "error: falló la compilación de hyprbars" >&2
    echo "—— diagnóstico —— " >&2
    echo "  hyprland:        ${running}" >&2
    echo "  hyprland-dev:    ${headers}" >&2
    echo "  hyprutils (pkg): ${sys_hu:-ausente} (Hyprland built against ${built_hu:-?})" >&2
    echo "  aquamarine:      ${sys_aq:-ausente} (Hyprland built against ${built_aq:-?})" >&2
    if grep -qE 'cannot convert.*(SP|PHLLS|CSyncTimeline)|explicit conversion function was not considered' "$BUILD_LOG"; then
        echo "  síntoma: incompatibilidad SharedPointer/WeakPointer (libhyprutils-dev demasiado nuevo)" >&2
        echo "  solución: headers en ${COMPAT_ROOT}/hyprutils-${built_hu:-X.Y.Z}/" >&2
    fi
    if grep -qE "unrecognized command-line option" "$BUILD_LOG"; then
        echo "  síntoma: flags de compilador no soportados" >&2
    fi
    echo "  log (últimas líneas):" >&2
    tail -n 40 "$BUILD_LOG" >&2 || true
    # Do not leave a half-wired desktop: remove stamp so the next run rebuilds.
    rm -f "$STAMP"
    exit 1
fi

install -Dm644 hyprbars.so "$PLUGIN"
printf '%s\n' "$running" >"$STAMP"
write_conf
ensure_source
echo "  → $PLUGIN"
echo "  → $CONF"

if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    if ! reload_and_check; then
        echo "error: el .so se generó pero Hyprland no cargó hyprbars" >&2
        echo "  Prueba: hyprctl plugin list ; hyprctl reload" >&2
        exit 1
    fi
else
    reload_and_check || true
fi
echo "Listo: barras de título con minimizar, maximizar y cerrar."
