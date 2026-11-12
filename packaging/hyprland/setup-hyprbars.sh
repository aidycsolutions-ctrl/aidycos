#!/usr/bin/env bash
# Build the hyprbars plugin (title bars with minimize / maximize / close) against
# the installed Hyprland. Debian's hyprland-plugin-hyprbars targets another ABI,
# so it is compiled locally from vendored hyprland-plugins sources (plus the
# drag-end patch already applied in packaging/hyprland/hyprbars-src).
#
# Owned by AidyCOS so test machines do not depend on Jugoo or on GitHub at
# apply time (flaky SSL on some laptops was leaving windows without buttons).
#
#   bash packaging/hyprland/setup-hyprbars.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGING="$ROOT/packaging/hyprland"
SRC="$PACKAGING/hyprbars-src"
HYPR_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
PLUGIN_DIR="$HOME/.local/lib/jugoo"
PLUGIN="$PLUGIN_DIR/hyprbars.so"
STAMP="$PLUGIN_DIR/hyprbars.hyprland-version"
CONF="$HYPR_HOME/config/jugoo_hyprbars.conf"
PACKAGES=(hyprland-dev pkgconf libpango1.0-dev libpixman-1-dev libudev-dev g++)

if [[ ! -f "$PACKAGING/jugoo_hyprbars.conf.in" ]]; then
    echo "error: falta ${PACKAGING}/jugoo_hyprbars.conf.in" >&2
    exit 1
fi
for needed in main.cpp barDeco.cpp barDeco.hpp BarPassElement.cpp BarPassElement.hpp globals.hpp; do
    if [[ ! -f "$SRC/$needed" ]]; then
        echo "error: faltan fuentes vendored de hyprbars en ${SRC}" >&2
        exit 1
    fi
done

running="$(dpkg-query -W -f='${Version}' hyprland 2>/dev/null || true)"
if [[ -z "$running" ]]; then
    echo "error: hyprland no está instalado" >&2
    exit 1
fi

write_conf() {
    mkdir -p "$(dirname "$CONF")"
    sed -e "s|@PLUGIN@|$PLUGIN|g" -e "s|@VENTANAS@|$HYPR_HOME/scripts/ventanas|g" \
        "$PACKAGING/jugoo_hyprbars.conf.in" >"$CONF"
    CSD="$(dirname "$CONF")/jugoo_hyprbars_csd.conf"
    if [[ ! -f "$CSD" ]]; then
        printf '%s\n' "# Generado por ventanas. No editar." >"$CSD"
    fi
}

# Prefer an already-built plugin when it matches this Hyprland version.
# Still refresh the conf so button commands point at the current ventanas path.
if [[ -f "$PLUGIN" && -f "$STAMP" && "$(cat "$STAMP")" == "$running" ]]; then
    write_conf
    echo "• hyprbars ya compilado para hyprland ${running}"
    echo "  → $PLUGIN"
    echo "  → $CONF"
    exit 0
fi
# Legacy installs (plugin without stamp): keep the .so, record the version, refresh conf.
if [[ -f "$PLUGIN" && ! -f "$STAMP" ]]; then
    printf '%s\n' "$running" >"$STAMP"
    write_conf
    echo "• hyprbars existente; se registró versión ${running}"
    echo "  → $PLUGIN"
    echo "  → $CONF"
    exit 0
fi

missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
    echo "• instalando dependencias: ${missing[*]}"
    # hyprland-dev lives in trixie-backports with hyprland itself.
    sudo apt-get install -y --no-install-recommends -t trixie-backports "${missing[@]}" \
        || sudo apt-get install -y --no-install-recommends "${missing[@]}"
fi

headers="$(dpkg-query -W -f='${Version}' hyprland-dev)"
if [[ "$running" != "$headers" ]]; then
    echo "error: hyprland ($running) y hyprland-dev ($headers) no coinciden" >&2
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/hyprbars"
cp -a "$SRC/." "$work/hyprbars/"

echo "• compilando hyprbars (fuentes locales, sin GitHub)"
cd "$work/hyprbars"
# shellcheck disable=SC2046
g++ -shared -fPIC -O2 -std=c++2b -Wno-c++11-narrowing --no-gnu-unique \
    $(pkg-config --cflags pixman-1 libdrm hyprland libinput libudev wayland-server xkbcommon pangocairo lua5.4) \
    main.cpp barDeco.cpp BarPassElement.cpp -o hyprbars.so
install -Dm644 hyprbars.so "$PLUGIN"
printf '%s\n' "$running" >"$STAMP"
write_conf
echo "  → $PLUGIN"
echo "  → $CONF"

if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload >/dev/null || true
    sleep 1
    hyprctl plugin list || true
fi
echo "Listo: barras de título con minimizar, maximizar y cerrar."
