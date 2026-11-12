#!/usr/bin/env python3
"""Apply the small local Jugoo additions used by the AidyCOS desktop profile."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import re
from pathlib import Path


def _load_network_model_snippets():
    """Load WIFI_* constants from shell/network_models.py without dumping models.py."""
    path = Path(__file__).parent / "shell" / "network_models.py"
    spec = importlib.util.spec_from_file_location("aidycos_network_models", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"No se pudo cargar el parche Wi-Fi: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(path: Path, old: str, new: str, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"No se pudo aplicar el ajuste Jugoo ({description}): {path}")
    backup = path.with_suffix(path.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def try_replace_once(path: Path, old: str, new: str, description: str) -> bool:
    """Like replace_once, but skip with a warning when the checkout already diverged."""
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        print(f"Aviso: se omite {description}: {path}", flush=True)
        return False
    backup = path.with_suffix(path.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def replace_desktop_icons_editor(root: Path, overlay: Path) -> None:
    pages = root / "shell/widgets/configuraciones/pages.py"
    editor_file = overlay / "widgets/configuraciones/desktop_icons_editor.py"
    editor = editor_file.read_text(encoding="utf-8")
    page_text = pages.read_text(encoding="utf-8")
    editor_start = page_text.find("\ndef _desktop_icons_editor(")
    if editor_start < 0 and page_text.startswith("def _desktop_icons_editor("):
        editor_start = 0
    if editor_start >= 0:
        editor_end = page_text.find("\ndef _wallpaper_editor(", editor_start)
        suffix = page_text[editor_end:] if editor_end >= 0 else ""
        updated_pages = page_text[:editor_start].rstrip() + "\n\n" + editor.rstrip() + "\n" + suffix
        if updated_pages != page_text:
            backup = pages.with_suffix(pages.suffix + ".aidycos-backup")
            if not backup.exists():
                shutil.copy2(pages, backup)
            pages.write_text(updated_pages, encoding="utf-8")
    else:
        with pages.open("a", encoding="utf-8") as stream:
            stream.write("\n\n" + editor.rstrip() + "\n")


def install_applications_menu(root: Path) -> None:
    """Bar button that opens the launcher; keep the pinned dock beside it."""
    overlay = Path(__file__).parent / "shell"
    install_overlay_file(
        overlay / "widgets/barra/applications.py",
        root / "shell/widgets/barra/applications.py",
    )

    # The dock already had a grid-looking “Anclar” control; use a + so it
    # does not look like a second applications launcher.
    pinned = root / "shell/widgets/barra/pinned_apps.py"
    if pinned.is_file():
        try_replace_once(
            pinned,
            '        self._expand_icon = Gtk.Image.new_from_icon_name(\n'
            '            "view-app-grid-symbolic",\n'
            "            Gtk.IconSize.DIALOG,\n"
            "        )\n",
            '        self._expand_icon = Gtk.Image.new_from_icon_name(\n'
            '            "list-add-symbolic",\n'
            "            Gtk.IconSize.DIALOG,\n"
            "        )\n",
            "distinguir el botón Anclar del lanzador de aplicaciones",
        )

    app = root / "shell/app.py"
    try_replace_once(
        app,
        "from .widgets.barra.pinned_apps import PinnedAppsWidget\n",
        "from .widgets.barra.applications import ApplicationsMenuWidget\n"
        "from .widgets.barra.pinned_apps import PinnedAppsWidget\n",
        "importar botón de aplicaciones",
    )
    # Apps grid + keep the pinned dock (pin from launcher, show on the bar).
    try_replace_once(
        app,
        "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n"
        "        self.layout.left.add(self.pinned_apps_widget)\n",
        "        self.applications_menu_widget = ApplicationsMenuWidget(self.toggle_launcher)\n"
        "        self.layout.left.add(self.applications_menu_widget)\n"
        "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n"
        "        self.layout.left.add(self.pinned_apps_widget)\n",
        "mostrar botón de aplicaciones junto al dock",
    )
    # If a previous AidyCOS pass removed the dock from the layout, put it back.
    try_replace_once(
        app,
        "        self.applications_menu_widget = ApplicationsMenuWidget(self.toggle_launcher)\n"
        "        self.layout.left.add(self.applications_menu_widget)\n"
        "        # Pinning stays available from the launcher; keep the widget for API compat.\n"
        "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n",
        "        self.applications_menu_widget = ApplicationsMenuWidget(self.toggle_launcher)\n"
        "        self.layout.left.add(self.applications_menu_widget)\n"
        "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n"
        "        self.layout.left.add(self.pinned_apps_widget)\n",
        "restaurar dock anclado junto al botón de aplicaciones",
    )

    layout = root / "shell/settings/layout_model.py"
    try_replace_once(
        layout,
        '    ModuleSlot("pinned_apps", "left", 1),\n'
        '    ModuleSlot("keyboard_cat", "left", 2),\n',
        '    ModuleSlot("applications_menu", "left", 1),\n'
        '    ModuleSlot("pinned_apps", "left", 2),\n'
        '    ModuleSlot("keyboard_cat", "left", 3),\n',
        "layout con botón de apps y dock anclado",
    )
    try_replace_once(
        layout,
        '    ModuleSlot("applications_menu", "left", 1),\n'
        '    ModuleSlot("keyboard_cat", "left", 2),\n',
        '    ModuleSlot("applications_menu", "left", 1),\n'
        '    ModuleSlot("pinned_apps", "left", 2),\n'
        '    ModuleSlot("keyboard_cat", "left", 3),\n',
        "restaurar pinned_apps en el layout por defecto",
    )

    style = root / "shell/style.css"
    style_text = style.read_text(encoding="utf-8")
    if "applications-menu-widget" not in style_text:
        css = """

/* AidyCOS: applications launcher button on the bar. */
window#shell box#shell-left > box.applications-menu-widget,
box.applications-menu-widget {
    margin-top: 4px;
    margin-bottom: 4px;
    padding: 2px 6px;
}

button.applications-menu-button {
    background: transparent;
    border: 0;
    box-shadow: none;
    min-width: 0;
    min-height: 0;
    padding: 4px;
    border-radius: 10px;
    color: @shell_text_primary;
}

button.applications-menu-button:hover {
    background-color: @shell_hover_bg;
}
"""
        backup = style.with_suffix(style.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(style, backup)
        style.write_text(style_text.rstrip() + "\n" + css, encoding="utf-8")


def ensure_desktop_icons_css(root: Path) -> None:
    """Keep the desktop layer transparent; opaque CSS made the whole desktop black."""
    style = root / "shell/style.css"
    text = style.read_text(encoding="utf-8")
    if "window#shell-desktop.desktop-layer" in text or "window.desktop-layer" in text:
        return
    css = """

/* AidyCOS: desktop icons layer must stay transparent over swaybg/hyprpaper. */
window#shell-desktop.desktop-layer,
window.desktop-layer {
    background-color: transparent;
}

eventbox.desktop-icon {
    background-color: transparent;
    border-radius: 10px;
    padding: 4px;
}

eventbox.desktop-icon:hover,
eventbox.desktop-icon.selected {
    background-color: alpha(@shell_accent, 0.18);
}

label.desktop-icon-label {
    color: @shell_text_primary;
    font-size: 11px;
    text-shadow: 0 1px 2px alpha(@shell_bg, 0.85);
}

box.settings-desktop-icons {
    background-color: alpha(@shell_accent, 0.08);
    border: 1px solid @shell_border_subtle;
    border-radius: 12px;
    padding: 10px 12px;
}
"""
    backup = style.with_suffix(style.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(style, backup)
    style.write_text(text.rstrip() + "\n" + css, encoding="utf-8")


def install_desktop_icons(root: Path) -> None:
    """Backport Jugoo's desktop-icon support when the published checkout is older."""
    overlay = Path(__file__).parent / "shell"
    for relative in (
        "servicios/escritorio/desktop_icons",
        "widgets/escritorio",
    ):
        source = overlay / relative
        target = root / "shell" / relative
        target.mkdir(parents=True, exist_ok=True)
        for item in source.glob("*.py"):
            destination = target / item.name
            if not destination.exists() or destination.read_bytes() != item.read_bytes():
                if destination.exists():
                    backup = destination.with_suffix(destination.suffix + ".aidycos-backup")
                    if not backup.exists():
                        shutil.copy2(destination, backup)
                shutil.copy2(item, destination)

    runtime_paths = root / "shell/runtime_paths.py"
    runtime_text = runtime_paths.read_text(encoding="utf-8")
    if "DESKTOP_ICONS_PATH" not in runtime_text:
        replace_once(
            runtime_paths,
            "from .config import CLIPBOARD_HISTORY_PATH, CLIPBOARD_IMAGES_DIR, PINNED_APPS_PATH, TASKS_PATH\n",
            "from .config import CLIPBOARD_HISTORY_PATH, CLIPBOARD_IMAGES_DIR, PINNED_APPS_PATH, TASKS_PATH, DESKTOP_ICONS_PATH\n",
            "importar la ruta de iconos del escritorio",
        )
    if "def desktop_icons_path(" not in runtime_text:
        replace_once(
            runtime_paths,
            "def tasks_path() -> Path:\n",
            "def desktop_icons_path() -> Path:\n"
            "    return xdg_data_dir() / DESKTOP_ICONS_PATH\n\n\n"
            "def tasks_path() -> Path:\n",
            "definir almacenamiento de iconos del escritorio",
        )
    identity = root / "shell/identity.py"
    identity_text = identity.read_text(encoding="utf-8")
    if "TITLE_DESKTOP" not in identity_text:
        replace_once(
            identity,
            "TITLE_PINNED_OVERFLOW = f\"{APPLICATION_NAME} Pinned Overflow\"\n",
            "TITLE_PINNED_OVERFLOW = f\"{APPLICATION_NAME} Pinned Overflow\"\n"
            "TITLE_DESKTOP = f\"{APPLICATION_NAME} Desktop Icons\"\n",
            "identificar la capa de iconos del escritorio",
        )
    if "TITLE_PHONE_PANEL" not in identity_text:
        try_replace_once(
            identity,
            'TITLE_NETWORK_PANEL = f"{APPLICATION_NAME} Network Panel"\n',
            'TITLE_NETWORK_PANEL = f"{APPLICATION_NAME} Network Panel"\n'
            'TITLE_PHONE_PANEL = f"{APPLICATION_NAME} Phone Panel"\n',
            "identificar el panel Teléfono del centro de control",
        )
    window_identity = root / "shell/window_identity.py"
    if window_identity.is_file():
        wi_text = window_identity.read_text(encoding="utf-8")
        if "TITLE_PHONE_PANEL" not in wi_text:
            try_replace_once(
                window_identity,
                "    TITLE_NETWORK_PANEL,\n",
                "    TITLE_NETWORK_PANEL,\n"
                "    TITLE_PHONE_PANEL,\n",
                "exportar TITLE_PHONE_PANEL",
            )

    config = root / "shell/config.py"
    config_text = config.read_text(encoding="utf-8")
    if "DESKTOP_ICONS_ENABLED" not in config_text:
        config_text = config_text.rstrip() + (
            "\n\n# AidyCOS: capa de iconos del escritorio (apagada por defecto).\n"
            "DESKTOP_ICONS_ENABLED = False\n"
            "DESKTOP_ICONS_PATH = \"desktop-icons.json\"\n"
            "DESKTOP_ICON_SIZE = 48\n"
            "DESKTOP_ICON_LABEL_WIDTH = 96\n"
            "DESKTOP_ICON_CELL_WIDTH = 104\n"
            "DESKTOP_ICON_CELL_HEIGHT = 96\n"
            "DESKTOP_ICON_DRAG_THRESHOLD_PX = 6\n"
        )
    else:
        # Keep desktop icons off; do not force-enable on overlay refresh.
        config_text = re.sub(
            r"^(\s*DESKTOP_ICONS_ENABLED\s*=\s*)True(\s*)$",
            r"\g<1>False\g<2>",
            config_text,
            count=1,
            flags=re.MULTILINE,
        )
        defaults = {
            "DESKTOP_ICONS_PATH": '"desktop-icons.json"',
            "DESKTOP_ICON_SIZE": "48",
            "DESKTOP_ICON_LABEL_WIDTH": "96",
            "DESKTOP_ICON_CELL_WIDTH": "104",
            "DESKTOP_ICON_CELL_HEIGHT": "96",
            "DESKTOP_ICON_DRAG_THRESHOLD_PX": "6",
        }
        for key, value in defaults.items():
            if not re.search(rf"^\s*{key}\s*=", config_text, re.MULTILINE):
                config_text += f"\n{key} = {value}\n"
    backup = config.with_suffix(config.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(config, backup)
    config.write_text(config_text, encoding="utf-8")

    app = root / "shell/app.py"
    app_text = app.read_text(encoding="utf-8")
    if (
        "self.desktop_icons = DesktopIconsService(" in app_text
        and "self.desktop_icons_layer = DesktopIconsLayer(" in app_text
    ):
        replace_desktop_icons_editor(root, overlay)
        ensure_desktop_icons_css(root)
        return
    replace_once(
        app,
        "from .config import (\n",
        "from .actions import dispatch_action\nfrom .config import (\n",
        "importar acciones para los accesos del escritorio",
    )
    replace_once(
        app,
        "from .servicios.escritorio.hyprland import HyprlandService\n",
        "from .servicios.escritorio.hyprland import HyprlandService\n"
        "from .servicios.escritorio.desktop_icons import DesktopIconsService\n",
        "importar servicio de iconos del escritorio",
    )
    replace_once(
        app,
        "from .widgets.barra.workspace import WorkspaceWidget\n",
        "from .widgets.barra.workspace import WorkspaceWidget\n"
        "from .widgets.escritorio.layer import DesktopIconsLayer\n",
        "importar capa de iconos del escritorio",
    )
    replace_once(
        app,
        "        self.applications = ApplicationsService(self.event_bus)\n",
        "        self.applications = ApplicationsService(self.event_bus)\n"
        "        self.desktop_icons = DesktopIconsService(\n"
        "            self.event_bus,\n"
        "            launch_application=self.applications.launch,\n"
        "            dispatch_action=lambda name: dispatch_action(name, self),\n"
        "        )\n"
        "        self.settings_manager.set_desktop_icons_service(self.desktop_icons)\n",
        "crear servicio de iconos del escritorio",
    )

    manager = root / "shell/settings/manager.py"
    replace_once(
        manager,
        "        self._workspace_hover_setter: Callable[[int], None] | None = None\n",
        "        self._workspace_hover_setter: Callable[[int], None] | None = None\n"
        "        self._desktop_icons = None\n"
        "        self._desktop_icons_enabled_setter: Callable[[bool], None] | None = None\n",
        "guardar referencias del servicio de iconos",
    )
    replace_once(
        manager,
        "    @property\n    def path(self) -> Path:\n",
        "    @property\n    def desktop_icons(self):\n"
        "        return self._desktop_icons\n\n"
        "    def set_desktop_icons_service(self, service) -> None:\n"
        "        self._desktop_icons = service\n\n"
        "    def set_desktop_icons_enabled_hook(self, callback: Callable[[bool], None]) -> None:\n"
        "        self._desktop_icons_enabled_setter = callback\n"
        "        self._hooks[\"escritorio.icons_enabled\"] = self._apply_desktop_icons_enabled\n\n"
        "    @property\n    def path(self) -> Path:\n",
        "exponer el servicio de iconos a configuración",
    )
    replace_once(
        manager,
        "    def _register_builtin_hooks(self) -> None:\n",
        "    def _apply_desktop_icons_enabled(\n"
        "        self, _manager: SettingsManager, _definition: SettingDef, value: Any\n"
        "    ) -> None:\n"
        "        if self._desktop_icons_enabled_setter is not None:\n"
        "            self._desktop_icons_enabled_setter(bool(value))\n\n"
        "    def _register_builtin_hooks(self) -> None:\n",
        "aplicar el ajuste de visibilidad de iconos",
    )

    app_icons = (
        "        self.settings_manager.start()\n\n"
        "        self.desktop_icons_layer = DesktopIconsLayer(\n"
        "            application, self.event_bus, self.desktop_icons\n"
        "        )\n"
        "        self.settings_manager.set_desktop_icons_enabled_hook(\n"
        "            self.desktop_icons_layer.set_enabled\n"
        "        )\n"
        "        self.desktop_icons.start()\n"
        "        enabled = bool(self.settings_manager.get(\"escritorio.icons_enabled\"))\n"
        "        self.desktop_icons_layer.set_enabled(enabled)\n"
        "        if enabled:\n"
        "            self.desktop_icons_layer.show_all()\n\n"
    )
    replace_once(
        app,
        "        self.settings_manager.start()\n\n",
        app_icons,
        "iniciar iconos del escritorio",
    )
    replace_once(
        app,
        "        self.applications.close()\n",
        "        self.applications.close()\n"
        "        self.desktop_icons.close()\n"
        "        if getattr(self, \"desktop_icons_layer\", None) is not None:\n"
        "            self.desktop_icons_layer.destroy()\n",
        "cerrar iconos del escritorio correctamente",
    )

    schema = root / "shell/settings/schema.py"
    schema_block = '''        SettingDef(
            key="escritorio.icons_enabled",
            category=CategoryId.TEMA,
            label="Mostrar iconos del escritorio",
            description="Capa de accesos sobre el fondo del escritorio.",
            value_type="bool",
            default=shell_config.DESKTOP_ICONS_ENABLED,
            config_attr="DESKTOP_ICONS_ENABLED",
            apply=APPLY_LIVE,
            tier="A",
            section="Escritorio",
        ),
        SettingDef(
            key="escritorio.icons_editor",
            category=CategoryId.TEMA,
            label="Accesos directos",
            description="Crear, mover o eliminar iconos del escritorio.",
            value_type="string",
            default="",
            apply=APPLY_LIVE,
            tier="A",
            section="Escritorio",
        ),
'''
    schema_text = schema.read_text(encoding="utf-8")
    if 'key="escritorio.icons_enabled"' not in schema_text:
        anchor = "    )\n\n\ndef settings_by_key"
        if anchor not in schema_text:
            raise SystemExit(f"No se pudo registrar la configuración de iconos: {schema}")
        schema_text = schema_text.replace(anchor, schema_block + anchor, 1)
        backup = schema.with_suffix(schema.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(schema, backup)
        schema.write_text(schema_text, encoding="utf-8")

    pages = root / "shell/widgets/configuraciones/pages.py"
    editor_file = overlay / "widgets/configuraciones/desktop_icons_editor.py"
    editor = editor_file.read_text(encoding="utf-8")
    replace_once(
        pages,
        "_CUSTOM_EDITOR_KEYS = frozenset(\n    {\n",
        "_CUSTOM_EDITOR_KEYS = frozenset(\n    {\n        \"escritorio.icons_editor\",\n",
        "registrar el editor de iconos",
    )
    replace_once(
        pages,
        "            elif definition.key == \"widgets.task_priorities_json\":\n"
        "                page.pack_start(_task_priorities_editor(manager, on_change), False, False, 0)\n",
        "            elif definition.key == \"widgets.task_priorities_json\":\n"
        "                page.pack_start(_task_priorities_editor(manager, on_change), False, False, 0)\n"
        "            elif definition.key == \"escritorio.icons_editor\":\n"
        "                page.pack_start(_desktop_icons_editor(manager), False, False, 0)\n",
        "mostrar el editor de iconos en configuración",
    )
    replace_desktop_icons_editor(root, overlay)
    ensure_desktop_icons_css(root)


def install_overlay_file(source: Path, destination: Path) -> None:
    if destination.exists() and destination.read_bytes() == source.read_bytes():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backup = destination.with_suffix(destination.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(destination, backup)
    shutil.copy2(source, destination)


def install_system_volume_read_fallback(audio: Path) -> None:
    """Ensure bar volume state can be read when pactl is down but wpctl works.

    Test PCs sometimes lack a working pipewire-pulse socket. Volume set/toggle
    already falls back to wpctl, but refresh used only pactl JSON — leaving
    system_volume as None and the bar icon stuck on the mute "x".
    """
    text = audio.read_text(encoding="utf-8")
    original = text

    if "def coerce_mute_flag(" not in text:
        helpers = '''
def coerce_mute_flag(value: Any) -> bool:
    """Parse pactl/wpctl mute fields that may be bool, int, or yes/no strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "muted"}:
        return True
    if text in {"", "0", "false", "no", "off", "unmuted"}:
        return False
    return False


def build_system_volume_state_from_wpctl(output: str) -> SystemVolumeState | None:
    """Parse `wpctl get-volume` text such as ``Volume: 0.81`` or ``Volume: 0.81 [MUTED]``."""
    text = str(output or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    muted = "[muted]" in lowered or lowered.endswith("muted")
    volume = None
    for token in text.replace("[", " ").replace("]", " ").split():
        try:
            volume = float(token)
            break
        except ValueError:
            continue
    if volume is None:
        return None
    clamped = max(0.0, min(1.5, volume))
    return SystemVolumeState(
        sink_name="@DEFAULT_AUDIO_SINK@",
        sink_description="Salida de audio",
        volume=min(1.0, clamped),
        is_muted=muted,
    )


'''
        anchor = "def build_system_volume_state(\n"
        if anchor not in text:
            print(f"Aviso: no se pudo añadir coerce_mute_flag: {audio}", flush=True)
        else:
            text = text.replace(anchor, helpers + anchor, 1)
            print("Aviso: se añadió coerce_mute_flag / wpctl volume parser", flush=True)

    # Prefer coerce_mute_flag over bool("no") == True.
    text = text.replace(
        "is_muted=bool(selected.get(\"mute\", False)),",
        "is_muted=coerce_mute_flag(selected.get(\"mute\", False)),",
    )
    text = text.replace(
        "is_muted = bool(item.get(\"mute\", False))",
        "is_muted = coerce_mute_flag(item.get(\"mute\", False))",
    )

    # Allow resolving volume from the first sink when get-default-sink is empty.
    old_guard = (
        "    \"\"\"Resolve default-sink volume/mute from pactl sink list JSON.\"\"\"\n"
        "    if not default_sink_name:\n"
        "        return None\n"
        "    target = default_sink_name.strip()\n"
        "    selected: dict[str, Any] | None = None\n"
        "    for item in sinks:\n"
        "        name = str(item.get(\"name\", \"\")).strip()\n"
        "        if name == target:\n"
        "            selected = item\n"
        "            break\n"
    )
    new_guard = (
        "    \"\"\"Resolve default-sink volume/mute from pactl sink list JSON.\"\"\"\n"
        "    target = str(default_sink_name or \"\").strip()\n"
        "    selected: dict[str, Any] | None = None\n"
        "    if target:\n"
        "        for item in sinks:\n"
        "            name = str(item.get(\"name\", \"\")).strip()\n"
        "            if name == target:\n"
        "                selected = item\n"
        "                break\n"
    )
    if old_guard in text:
        text = text.replace(old_guard, new_guard, 1)
        print("Aviso: build_system_volume_state acepta sink por defecto vacío", flush=True)

    if "def _query_system_volume_wpctl(" not in text:
        wpctl_method = '''
    def _query_system_volume_wpctl(self) -> SystemVolumeState | None:
        """Read default sink volume/mute via wpctl when pactl JSON is unavailable."""
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return build_system_volume_state_from_wpctl(result.stdout)

'''
        marker = "    def _query_pactl_json(self, target: str) -> list[dict[str, Any]]:\n"
        if marker not in text:
            print(f"Aviso: no se pudo añadir _query_system_volume_wpctl: {audio}", flush=True)
        else:
            text = text.replace(marker, wpctl_method + marker, 1)
            print("Aviso: se añadió lectura de volumen vía wpctl", flush=True)

    if "self._query_system_volume_wpctl()" not in text:
        old_refresh = (
            "        system_volume = build_system_volume_state(\n"
            "            sinks_raw,\n"
            "            self._query_default_sink_name(),\n"
            "        )\n"
            "        new_snapshot = AudioSnapshot(\n"
        )
        new_refresh = (
            "        system_volume = build_system_volume_state(\n"
            "            sinks_raw,\n"
            "            self._query_default_sink_name(),\n"
            "        )\n"
            "        if system_volume is None:\n"
            "            # pipewire-pulse/pactl may be down while native PipeWire (wpctl) works.\n"
            "            system_volume = self._query_system_volume_wpctl()\n"
            "        new_snapshot = AudioSnapshot(\n"
        )
        if old_refresh not in text:
            print(f"Aviso: no se pudo enganchar fallback wpctl en refresh: {audio}", flush=True)
        else:
            text = text.replace(old_refresh, new_refresh, 1)
            print("Aviso: refresh de audio usa wpctl si pactl no da system_volume", flush=True)

    if text == original:
        return
    backup = audio.with_suffix(audio.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(audio, backup)
    audio.write_text(text, encoding="utf-8")



def install_battery(root: Path) -> None:
    """Backport the UPower/sysfs battery indicator on older Jugoo checkouts."""
    overlay = Path(__file__).parent / "shell"
    for relative in (
        Path("servicios/energia/battery.py"),
        Path("widgets/barra/battery.py"),
    ):
        install_overlay_file(overlay / relative, root / "shell" / relative)

    models = root / "shell/models.py"
    if "class BatterySnapshot:" not in models.read_text(encoding="utf-8"):
        snippet = (overlay / "battery_model.py").read_text(encoding="utf-8")
        replace_once(
            models,
            "@dataclass(frozen=True)\nclass NetworkInterfaceSnapshot:\n",
            snippet + "\n\n@dataclass(frozen=True)\nclass NetworkInterfaceSnapshot:\n",
            "añadir el modelo de estado de batería",
        )

    config = root / "shell/config.py"
    config_text = config.read_text(encoding="utf-8")
    for key, value in {
        "BATTERY_ICON_SIZE": "16",
        "BATTERY_POLL_INTERVAL_SEC": "30",
        "BATTERY_VISIBILITY": '"auto"',
        "BATTERY_LOW_PERCENT": "20",
        "BATTERY_CRITICAL_PERCENT": "10",
    }.items():
        if not re.search(rf"^\s*{key}\s*=", config_text, re.MULTILINE):
            config_text += f"\n{key} = {value}\n"
    if config_text != config.read_text(encoding="utf-8"):
        backup = config.with_suffix(config.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(config, backup)
        config.write_text(config_text, encoding="utf-8")

    app = root / "shell/app.py"
    app_text = app.read_text(encoding="utf-8")
    if "self.battery_service = BatteryService(" in app_text:
        return
    replace_once(
        app,
        "from .servicios.energia.power import PowerService\n",
        "from .servicios.energia.power import PowerService\n"
        "from .servicios.energia.battery import BatteryService\n",
        "importar servicio de batería",
    )
    replace_once(
        app,
        "from .widgets.barra.ethernet import EthernetWidget\n",
        "from .widgets.barra.ethernet import EthernetWidget\n"
        "from .widgets.barra.battery import BatteryWidget\n",
        "importar indicador de batería",
    )
    replace_once(
        app,
        "        self.power_service = PowerService()\n",
        "        self.power_service = PowerService()\n"
        "        self.battery_service = BatteryService(self.event_bus)\n",
        "crear servicio de batería",
    )
    replace_once(
        app,
        "        self.ethernet_widget = EthernetWidget(self.event_bus, self.network_service)\n",
        "        self.ethernet_widget = EthernetWidget(self.event_bus, self.network_service)\n"
        "        self.battery_widget = BatteryWidget(self.event_bus, self.battery_service)\n",
        "crear indicador de batería",
    )
    replace_once(
        app,
        "        self.layout.right.add(self.ethernet_widget)\n",
        "        self.layout.right.add(self.ethernet_widget)\n"
        "        self.layout.right.add(self.battery_widget)\n",
        "mostrar indicador de batería",
    )
    replace_once(
        app,
        "        self.hyprland.start()\n",
        "        self.hyprland.start()\n        self.battery_service.start()\n",
        "iniciar monitoreo de batería",
    )
    replace_once(
        app,
        "        self.network_service.close()\n",
        "        self.network_service.close()\n        self.battery_service.close()\n",
        "cerrar monitoreo de batería",
    )

    schema = root / "shell/settings/schema.py"
    schema_text = schema.read_text(encoding="utf-8")
    if 'key="widgets.battery_visibility"' not in schema_text:
        battery_setting = '''        SettingDef(
            key="widgets.battery_visibility",
            category=CategoryId.WIDGETS,
            label="Indicador de batería",
            description="Automático muestra el nivel si el equipo tiene batería.",
            value_type="choice",
            default=shell_config.BATTERY_VISIBILITY,
            config_attr="BATTERY_VISIBILITY",
            apply=APPLY_LIVE,
            choices=(("auto", "Automático"), ("always", "Siempre"), ("never", "Nunca")),
            tier="A",
            section="Batería",
        ),
'''
        anchor = "    )\n\n\ndef settings_by_key"
        if anchor not in schema_text:
            raise SystemExit(f"No se pudo registrar el indicador de batería: {schema}")
        schema_text = schema_text.replace(anchor, battery_setting + anchor, 1)
        backup = schema.with_suffix(schema.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(schema, backup)
        schema.write_text(schema_text, encoding="utf-8")


def install_network_wifi(root: Path) -> None:
    """Backport Wi-Fi reconnect/scan/connect/share/forget onto older Jugoo checkouts."""
    overlay = Path(__file__).parent / "shell"
    for relative in (
        Path("servicios/red/network.py"),
        Path("servicios/red/network_hotspot.py"),
        Path("servicios/red/wifi_connect_plan.py"),
        Path("widgets/centro_control/network_section.py"),
    ):
        source = overlay / relative
        if source.is_file():
            install_overlay_file(source, root / "shell" / relative)
    # Only replace the control-center popup when the phone/movil stack is present.
    # The overlay popup imports shell.servicios.movil; shipping it alone breaks Jugoo.
    popup_source = overlay / "widgets/centro_control/popup.py"
    movil_ready = (root / "shell/servicios/movil/kdeconnect.py").is_file() and (
        root / "shell/widgets/centro_control/phone_section.py"
    ).is_file()
    if popup_source.is_file() and movil_ready:
        install_overlay_file(
            popup_source,
            root / "shell/widgets/centro_control/popup.py",
        )
    elif popup_source.is_file():
        print(
            "Aviso: se omite popup.py del centro de control "
            "(falta shell/servicios/movil o phone_section).",
            flush=True,
        )

    models = root / "shell/models.py"
    models_text = models.read_text(encoding="utf-8")
    snippets = _load_network_model_snippets()
    saved_field = snippets.WIFI_ACCESS_POINT_SAVED_FIELD
    credentials_snippet = snippets.WIFI_CREDENTIALS_SNIPPET.strip("\n") + "\n"
    credentials_marker = "class WifiCredentials:"
    needs_saved = (
        "class WifiAccessPointSnapshot:" in models_text
        and "saved: bool = False" not in models_text
    )
    needs_credentials = credentials_marker not in models_text

    if needs_saved and needs_credentials:
        replace_once(
            models,
            "    active: bool = False\n\n\n@dataclass(frozen=True)\nclass HotspotClientSnapshot:\n",
            f"    active: bool = False\n{saved_field}\n\n"
            f"{credentials_snippet}\n\n@dataclass(frozen=True)\nclass HotspotClientSnapshot:\n",
            "añadir WifiAccessPointSnapshot.saved y WifiCredentials",
        )
    elif needs_credentials:
        if "class HotspotClientSnapshot:" in models_text:
            replace_once(
                models,
                "@dataclass(frozen=True)\nclass HotspotClientSnapshot:\n",
                f"{credentials_snippet}\n\n@dataclass(frozen=True)\nclass HotspotClientSnapshot:\n",
                "añadir WifiCredentials",
            )
        else:
            print(f"Aviso: se omite el parche de WifiCredentials: {models}", flush=True)
    elif needs_saved:
        try_replace_once(
            models,
            "    active: bool = False\n",
            f"    active: bool = False\n{saved_field}",
            "añadir WifiAccessPointSnapshot.saved",
        )

    popup = root / "shell/widgets/centro_control/popup.py"
    if popup.is_file():
        popup_text = popup.read_text(encoding="utf-8")
        # Broken AidyCOS/older Jugoo wiring: lambda only took (path, password), but
        # network_section passes (path, password, ssid). That TypeError swallowed
        # every UI connect while plain `nmcli device wifi connect` still worked.
        broken_lambda = (
            "                on_connect_wifi=lambda path, password: "
            "network_service.connect_wifi(\n"
            "                    path,\n"
            "                    password,\n"
            "                ),\n"
        )
        fixed_connect = "                on_connect_wifi=network_service.connect_wifi,\n"
        if broken_lambda in popup_text:
            try_replace_once(
                popup,
                broken_lambda,
                fixed_connect,
                "pasar SSID al conectar Wi-Fi desde el centro de control",
            )
            popup_text = popup.read_text(encoding="utf-8")
        elif (
            "on_connect_wifi=lambda path, password:" in popup_text
            and "on_connect_wifi=network_service.connect_wifi," not in popup_text
        ):
            try_replace_once(
                popup,
                "                on_connect_wifi=lambda path, password: network_service.connect_wifi(\n"
                "                    path,\n"
                "                    password,\n"
                "                ),\n",
                fixed_connect,
                "pasar SSID al conectar Wi-Fi desde el centro de control",
            )
            popup_text = popup.read_text(encoding="utf-8")

        if "on_forget_wifi=" not in popup_text:
            patched = try_replace_once(
                popup,
                "                on_apply_hotspot=network_service.apply_hotspot_config,\n"
                "            )\n",
                "                on_apply_hotspot=network_service.apply_hotspot_config,\n"
                "                on_forget_wifi=network_service.forget_wifi,\n"
                "                on_request_wifi_credentials="
                "network_service.request_active_wifi_credentials,\n"
                "            )\n",
                "conectar forget/share Wi-Fi en el centro de control",
            )
            if not patched:
                try_replace_once(
                    popup,
                    "                on_apply_hotspot=network_service.apply_hotspot_config,\n",
                    "                on_apply_hotspot=network_service.apply_hotspot_config,\n"
                    "                on_forget_wifi=network_service.forget_wifi,\n"
                    "                on_request_wifi_credentials="
                    "network_service.request_active_wifi_credentials,\n",
                    "conectar forget/share Wi-Fi en el centro de control",
                )
            elif "on_request_wifi_credentials=" not in popup.read_text(encoding="utf-8"):
                try_replace_once(
                    popup,
                    "                on_forget_wifi=network_service.forget_wifi,\n",
                    "                on_forget_wifi=network_service.forget_wifi,\n"
                    "                on_request_wifi_credentials="
                    "network_service.request_active_wifi_credentials,\n",
                    "conectar request_wifi_credentials en el centro de control",
                )

    style = root / "shell/style.css"
    style_text = style.read_text(encoding="utf-8")
    css_parts: list[str] = []
    if "control-center-wifi-share" not in style_text:
        css_parts.append(
            "\nbox.control-center-wifi-share {\n"
            "    padding: 6px 0;\n"
            "}\n"
        )
    if "control-center-wifi-list" not in style_text:
        css_parts.append(
            "\nlistbox.control-center-wifi-list {\n"
            "    background: transparent;\n"
            "}\n"
            "\nrow.control-center-wifi-row {\n"
            "    border-radius: 8px;\n"
            "    margin: 2px 0;\n"
            "}\n"
            "\nrow.control-center-wifi-row-active {\n"
            "    background-color: @shell_hover_bg_faint;\n"
            "}\n"
            "\nlabel.control-center-wifi-ssid {\n"
            "    color: @shell_text_primary;\n"
            "}\n"
        )
    if css_parts:
        backup = style.with_suffix(style.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(style, backup)
        style.write_text(style_text.rstrip() + "".join(css_parts), encoding="utf-8")


def install_printers(root: Path) -> None:
    """Add Configuraciones → Impresoras (CUPS list + system-config-printer)."""
    overlay = Path(__file__).parent / "shell"
    for relative in (
        Path("servicios/impresoras/__init__.py"),
        Path("servicios/impresoras/service.py"),
        Path("widgets/configuraciones/printers_page.py"),
    ):
        install_overlay_file(overlay / relative, root / "shell" / relative)

    schema = root / "shell/settings/schema.py"
    schema_text = schema.read_text(encoding="utf-8")
    if "IMPRESORAS" not in schema_text:
        try_replace_once(
            schema,
            '    ATAJOS = "atajos"\n    AVANZADO = "avanzado"\n',
            '    ATAJOS = "atajos"\n'
            '    IMPRESORAS = "impresoras"\n'
            '    AVANZADO = "avanzado"\n',
            "registrar categoría Impresoras",
        )
        try_replace_once(
            schema,
            '    CategoryId.ATAJOS: ("Atajos", "Atajos de teclado activos (solo lectura)"),\n'
            '    CategoryId.AVANZADO: ("Avanzado", "Rendimiento e integraciones"),\n',
            '    CategoryId.ATAJOS: ("Atajos", "Atajos de teclado activos (solo lectura)"),\n'
            '    CategoryId.IMPRESORAS: (\n'
            '        "Impresoras",\n'
            '        "Gestionar impresoras CUPS y compartir el catálogo con otros PCs.",\n'
            "    ),\n"
            '    CategoryId.AVANZADO: ("Avanzado", "Rendimiento e integraciones"),\n',
            "añadir metadatos de Impresoras",
        )
    else:
        try_replace_once(
            schema,
            '"Gestionar impresoras CUPS y abrir el gestor del sistema."',
            '"Gestionar impresoras CUPS y compartir el catálogo con otros PCs."',
            "actualizar descripción de Impresoras",
        )

    pages = root / "shell/widgets/configuraciones/pages.py"
    try_replace_once(
        pages,
        "from .shortcuts_page import build_shortcuts_page\n",
        "from .printers_page import build_printers_page\n"
        "from .shortcuts_page import build_shortcuts_page\n",
        "importar página de impresoras",
    )
    try_replace_once(
        pages,
        "    if category is CategoryId.ATAJOS:\n"
        "        return build_shortcuts_page()\n",
        "    if category is CategoryId.ATAJOS:\n"
        "        return build_shortcuts_page()\n"
        "    if category is CategoryId.IMPRESORAS:\n"
        "        return build_printers_page()\n",
        "mostrar página de impresoras",
    )

    # Insert catalog-free Impresoras next to Atajos (before Avanzado).
    pane = root / "shell/widgets/configuraciones/pane.py"
    pane_text = pane.read_text(encoding="utf-8")
    if "IMPRESORAS" not in pane_text:
        old_ordered = '''def ordered_categories(manager: SettingsManager) -> tuple[CategoryId, ...]:
    """Nav order for the live Settings UI (launcher settings mode).

    ``CategoryId.ATAJOS`` is catalog-free (no SettingDef) so it never appears in
    ``categories_present()``; insert it once before Avanzado for the real menu.
    """
    ordered = (CategoryId.GENERAL,) + tuple(
        category
        for category in manager.categories_present()
        if category is not CategoryId.GENERAL
    )
    if CategoryId.ATAJOS in ordered:
        return ordered
    insert_at = len(ordered)
    for index, category in enumerate(ordered):
        if category is CategoryId.AVANZADO:
            insert_at = index
            break
    return ordered[:insert_at] + (CategoryId.ATAJOS,) + ordered[insert_at:]
'''
        new_ordered = '''def ordered_categories(manager: SettingsManager) -> tuple[CategoryId, ...]:
    """Nav order for the live Settings UI (launcher settings mode).

    Catalog-free categories (Atajos, Impresoras) never appear in
    ``categories_present()``; insert them once before Avanzado.
    """
    ordered = (CategoryId.GENERAL,) + tuple(
        category
        for category in manager.categories_present()
        if category is not CategoryId.GENERAL
    )
    extras = []
    if CategoryId.ATAJOS not in ordered:
        extras.append(CategoryId.ATAJOS)
    if hasattr(CategoryId, "IMPRESORAS") and CategoryId.IMPRESORAS not in ordered:
        extras.append(CategoryId.IMPRESORAS)
    if not extras:
        return ordered
    insert_at = len(ordered)
    for index, category in enumerate(ordered):
        if category is CategoryId.AVANZADO:
            insert_at = index
            break
    return ordered[:insert_at] + tuple(extras) + ordered[insert_at:]
'''
        if old_ordered in pane_text:
            backup = pane.with_suffix(pane.suffix + ".aidycos-backup")
            if not backup.exists():
                shutil.copy2(pane, backup)
            pane.write_text(pane_text.replace(old_ordered, new_ordered, 1), encoding="utf-8")
        else:
            print(f"Aviso: se omite el orden de Impresoras en pane.py: {pane}", flush=True)

    settings_overlay = root / "shell/widgets/configuraciones/overlay.py"
    overlay_text = settings_overlay.read_text(encoding="utf-8")
    if "IMPRESORAS" not in overlay_text:
        old_block = '''        # Atajos is catalog-free (read-only registry page); always offer it.
        if CategoryId.ATAJOS not in ordered:
            insert_at = len(ordered)
            for index, cat in enumerate(ordered):
                if cat is CategoryId.AVANZADO:
                    insert_at = index
                    break
            ordered = ordered[:insert_at] + (CategoryId.ATAJOS,) + ordered[insert_at:]
'''
        new_block = '''        # Catalog-free pages (Atajos, Impresoras); always offer them.
        extras = []
        if CategoryId.ATAJOS not in ordered:
            extras.append(CategoryId.ATAJOS)
        if hasattr(CategoryId, "IMPRESORAS") and CategoryId.IMPRESORAS not in ordered:
            extras.append(CategoryId.IMPRESORAS)
        if extras:
            insert_at = len(ordered)
            for index, cat in enumerate(ordered):
                if cat is CategoryId.AVANZADO:
                    insert_at = index
                    break
            ordered = ordered[:insert_at] + tuple(extras) + ordered[insert_at:]
'''
        if old_block in overlay_text:
            backup = settings_overlay.with_suffix(settings_overlay.suffix + ".aidycos-backup")
            if not backup.exists():
                shutil.copy2(settings_overlay, backup)
            settings_overlay.write_text(
                overlay_text.replace(old_block, new_block, 1),
                encoding="utf-8",
            )
        else:
            print(
                f"Aviso: se omite el menú de Impresoras en overlay.py: {settings_overlay}",
                flush=True,
            )

    style = root / "shell/style.css"
    style_text = style.read_text(encoding="utf-8")
    if "settings-printer-row" not in style_text:
        css = (
            "\nbox.settings-printer-row {\n"
            "    padding: 8px 0;\n"
            "    border-bottom: 1px solid alpha(@shell_text_primary, 0.12);\n"
            "}\n"
        )
        backup = style.with_suffix(style.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(style, backup)
        style.write_text(style_text.rstrip() + "\n" + css, encoding="utf-8")


def install_native_window_focus(root: Path) -> None:
    """Dock/launcher clicks must raise floating windows, not only steal focus.

    Upstream Jugoo sometimes dispatches a Lua ``hl.dsp.focus`` expression that
    Hyprland ignores; even a plain ``focuswindow`` can leave another float on
    top. Always use ``focuswindow`` + ``alterzorder top``.
    """
    service = root / "shell/servicios/escritorio/hyprland.py"
    if not service.is_file():
        return
    text = service.read_text(encoding="utf-8")
    marker = "# AidyCOS: native focuswindow + alterzorder for dock clicks."
    if marker in text:
        return
    pattern = re.compile(
        r"    def _focus_window\(self, address: str\) -> None:\n"
        r"(?:.*\n)*?"
        r"(?=    def )",
    )
    match = pattern.search(text)
    if match is None:
        print(
            f"Aviso: no se ajustó el foco de ventanas (API distinta): {service}",
            flush=True,
        )
        return
    replacement = f'''    def _focus_window(self, address: str) -> None:
        {marker}
        def dispatch(dispatcher: str, argument: str | None = None) -> None:
            command = ["hyprctl", "dispatch", dispatcher]
            if argument:
                command.append(argument)
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                stderr = ""
                if isinstance(error, subprocess.CalledProcessError):
                    stderr = (error.stderr or error.stdout or "").strip()
                detail = f": {{stderr}}" if stderr else ""
                raise HyprlandError(f"could not execute Hyprland dispatch{{detail}}") from error

        dispatch("focuswindow", f"address:{{address}}")
        dispatch("alterzorder", f"top,address:{{address}}")

'''
    backup = service.with_suffix(service.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(service, backup)
    service.write_text(text[: match.start()] + replacement + text[match.end() :], encoding="utf-8")


def install_native_workspace_dispatch(root: Path) -> None:
    """Use Hyprland's built-in workspace dispatcher for strip clicks."""
    service = root / "shell/servicios/escritorio/hyprland.py"
    text = service.read_text(encoding="utf-8")
    marker = "# AidyCOS: standard Hyprland workspace dispatch."
    if marker in text:
        return
    pattern = re.compile(
        r"    def _dispatch_workspace\(\n.*?(?=    @staticmethod\n"
        r"    def _special_workspace_expression)",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        # Newer Jugoo checkouts may already use a different workspace dispatcher.
        print(
            f"Aviso: no se ajustó el dispatcher de escritorios (API distinta): {service}",
            flush=True,
        )
        return
    replacement = '''    def _dispatch_workspace(
        self,
        workspace_id: int,
        workspace_name: str | None,
        is_special: bool,
    ) -> None:
        def dispatch(dispatcher: str, argument: str | None = None) -> None:
            command = ["hyprctl", "dispatch", dispatcher]
            if argument:
                command.append(argument)
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                stderr = ""
                if isinstance(error, subprocess.CalledProcessError):
                    stderr = (error.stderr or error.stdout or "").strip()
                detail = f": {stderr}" if stderr else ""
                raise HyprlandError(f"could not execute Hyprland workspace dispatch{detail}") from error

        if is_special:
            special_name = (workspace_name or "").partition(":")[2]
            dispatch("togglespecialworkspace", special_name if special_name not in ("", "special") else None)
            return

        for special_name in self._get_visible_special_workspace_names():
            dispatch("togglespecialworkspace", special_name.partition(":")[2] or None)

        target = workspace_name or str(workspace_id)
        if not target.isdecimal() and not target.startswith("name:"):
            target = f"name:{target}"
        dispatch("workspace", target)

'''
    backup = service.with_suffix(service.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(service, backup)
    service.write_text(
        text[:match.start()]
        + "    " + marker + "\n"
        + replacement
        + text[match.end():],
        encoding="utf-8",
    )


def install_bar_position(root: Path) -> None:
    """Configuraciones → Barra → Posición (arriba / abajo / izquierda / derecha)."""
    overlay = Path(__file__).parent / "shell"
    install_overlay_file(overlay / "bar_position.py", root / "shell/bar_position.py")
    install_overlay_file(overlay / "layout.py", root / "shell/layout.py")

    config = root / "shell/config.py"
    config_text = config.read_text(encoding="utf-8")
    if "BAR_POSITION" not in config_text:
        try_replace_once(
            config,
            "# Layer-shell top inset. 0 anchors the bar flush with the monitor edge (y=0).\n"
            "TOP_MARGIN = 0\n",
            "# Layer-shell edge for the bar: top | bottom | left | right.\n"
            'BAR_POSITION = "top"\n'
            "# Layer-shell inset on the active edge. 0 anchors flush with the monitor.\n"
            "TOP_MARGIN = 0\n",
            "añadir BAR_POSITION en config",
        )

    schema = root / "shell/settings/schema.py"
    schema_text = schema.read_text(encoding="utf-8")
    if 'key="barra.position"' not in schema_text:
        setting = '''        SettingDef(
            key="barra.position",
            category=CategoryId.BARRA,
            label="Posición de la barra",
            description="Borde del monitor donde se coloca la barra Jugoo.",
            value_type="choice",
            default=getattr(shell_config, "BAR_POSITION", "top"),
            config_attr="BAR_POSITION",
            apply=APPLY_RELOAD,
            choices=(
                ("top", "Arriba"),
                ("bottom", "Abajo"),
                ("left", "Izquierda"),
                ("right", "Derecha"),
            ),
            tier="A",
            section="Geometría",
        ),
'''
        # Prefer inserting just before the top-margin control when present.
        margin_anchor = '        SettingDef(\n            key="barra.top_margin",'
        if margin_anchor in schema_text:
            schema_text = schema_text.replace(margin_anchor, setting + margin_anchor, 1)
        else:
            anchor = "    )\n\n\ndef settings_by_key"
            if anchor not in schema_text:
                raise SystemExit(f"No se pudo registrar barra.position: {schema}")
            schema_text = schema_text.replace(anchor, setting + anchor, 1)
        backup = schema.with_suffix(schema.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(schema, backup)
        schema.write_text(schema_text, encoding="utf-8")

    try_replace_once(
        schema,
        '            label="Margen superior",\n'
        '            description="Inset de la barra respecto al borde del monitor.",\n',
        '            label="Margen del borde",\n'
        '            description="Inset de la barra respecto al borde elegido.",\n',
        "renombrar margen de la barra",
    )

    identity = root / "shell/window_identity.py"
    try_replace_once(
        identity,
        '    """Top-left popup coordinates: centered on the anchor, top below the button."""\n'
        "    edge = shell_config.POPUP_EDGE_MARGIN if margin is None else margin\n"
        "    popup_left = button_center_x - popup_width // 2\n"
        "    popup_top = fixed_top if fixed_top is not None else button_bottom + offset\n"
        "\n"
        "    if monitor is not None:\n"
        "        mon_left = monitor.x\n"
        "        mon_top = monitor.y\n"
        "        mon_right = monitor.x + monitor.width\n"
        "        mon_bottom = monitor.y + monitor.height\n"
        "\n"
        "        popup_left = max(\n"
        "            mon_left + edge,\n"
        "            min(popup_left, mon_right - popup_width - edge),\n"
        "        )\n"
        "        # Never slide the window up to fit a taller size: that overlaps the bar.\n"
        "        # Popups grow downward; content that does not fit scrolls.\n"
        "        popup_top = max(mon_top + edge, popup_top)\n"
        "\n"
        "    return int(popup_left), int(popup_top)\n",
        '    """Top-left popup coordinates relative to the configured bar edge."""\n'
        "    from .bar_position import compute_popup_for_bar\n"
        "\n"
        "    return compute_popup_for_bar(\n"
        "        button_left=button_center_x,\n"
        "        button_top=button_bottom - 1,\n"
        "        button_width=1,\n"
        "        button_height=1,\n"
        "        popup_width=popup_width,\n"
        "        popup_height=popup_height,\n"
        "        offset=offset,\n"
        "        fixed_top=fixed_top,\n"
        "        monitor=monitor,\n"
        "        margin=margin,\n"
        "    )\n",
        "posicionar popups según el borde de la barra",
    )
    try_replace_once(
        identity,
        '    """Position a popup from anchor geometry and popup size; return the top edge used."""\n'
        "    geometry = anchor_button_geometry(anchor)\n"
        "    if geometry is None:\n"
        "        return None\n"
        "\n"
        "    popup_width, popup_height = popup_window_size(window)\n"
        "    monitor = monitor_containing_point(geometry.center_x, geometry.bottom)\n"
        "    popup_left, popup_top = compute_popup_top_left(\n"
        "        button_center_x=geometry.center_x,\n"
        "        button_bottom=geometry.bottom,\n"
        "        popup_width=popup_width,\n"
        "        popup_height=popup_height,\n"
        "        offset=offset + extra_y_offset,\n"
        "        fixed_top=(fixed_top + extra_y_offset) if fixed_top is not None else None,\n"
        "        monitor=monitor,\n"
        "        margin=margin,\n"
        "    )\n"
        "    reposition_popup(window, title=title, x=popup_left, y=popup_top)\n"
        "    return popup_top\n",
        '    """Position a popup from anchor geometry and popup size; return the top edge used."""\n'
        "    from .bar_position import compute_popup_for_bar\n"
        "\n"
        "    geometry = anchor_button_geometry(anchor)\n"
        "    if geometry is None:\n"
        "        return None\n"
        "\n"
        "    popup_width, popup_height = popup_window_size(window)\n"
        "    monitor = monitor_containing_point(geometry.center_x, geometry.bottom)\n"
        "    popup_left, popup_top = compute_popup_for_bar(\n"
        "        button_left=geometry.left,\n"
        "        button_top=geometry.top,\n"
        "        button_width=geometry.width,\n"
        "        button_height=geometry.height,\n"
        "        popup_width=popup_width,\n"
        "        popup_height=popup_height,\n"
        "        offset=offset + extra_y_offset,\n"
        "        fixed_top=(fixed_top + extra_y_offset) if fixed_top is not None else None,\n"
        "        monitor=monitor,\n"
        "        margin=margin,\n"
        "    )\n"
        "    reposition_popup(window, title=title, x=popup_left, y=popup_top)\n"
        "    return popup_top\n",
        "anclar popups al botón con la posición de barra",
    )

    app = root / "shell/app.py"
    _patch_app_bar_position(app)

    style = root / "shell/style.css"
    style_text = style.read_text(encoding="utf-8")
    if "shell-bar-vertical" not in style_text:
        css = """

/* AidyCOS: vertical bar (left / right edge). */
box.shell-bar.shell-bar-vertical {
    box-shadow:
        1px 0 0 @shell_glass_highlight,
        3px 0 10px @shell_shadow_soft;
}

box.shell-bar.shell-bar-vertical box#shell-center,
box.shell-bar.shell-bar-vertical box#shell-right {
    margin-top: 0;
    margin-bottom: 0;
    margin-left: 4px;
    margin-right: 4px;
}

box.shell-bar.shell-bar-vertical box.shell-module {
    margin: 3px 0;
}
"""
        backup = style.with_suffix(style.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(style, backup)
        style.write_text(style_text.rstrip() + "\n" + css, encoding="utf-8")


def _patch_app_bar_position(app: Path) -> None:
    """Wire bar-position helpers into app.py without dropping TOP_MARGIN early.

    Older AidyCOS /opt checkouts lack ``set_monitor`` inside
    ``_configure_layer_shell``. A previous overlay pass removed the
    ``TOP_MARGIN`` import before that method was rewritten, which crashed
    Jugoo at startup with ``NameError: TOP_MARGIN``.
    """
    text = app.read_text(encoding="utf-8")
    original = text

    bar_import = (
        "from .bar_position import (\n"
        "    apply_bar_expand_flags,\n"
        "    apply_bar_size_requests,\n"
        "    configure_bar_layer_shell,\n"
        ")\n"
    )
    if "from .bar_position import" not in text:
        config_import = (
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            "    TOP_MARGIN,\n"
            ")\n"
        )
        config_import_no_margin = (
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            ")\n"
        )
        if config_import in text:
            text = text.replace(config_import, bar_import + config_import, 1)
        elif config_import_no_margin in text:
            # Repair a half-applied install: keep helpers and restore TOP_MARGIN.
            text = text.replace(
                config_import_no_margin,
                bar_import + config_import,
                1,
            )
        else:
            print(f"Aviso: se omite import de posición de barra: {app}", flush=True)

    configure_new = (
        "    def _configure_layer_shell(self) -> None:\n"
        "        GtkLayerShell.init_for_window(self)\n"
        "        GtkLayerShell.set_namespace(self, APP_ID)\n"
        "        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)\n"
        "        configure_bar_layer_shell(self)\n"
        "        GtkLayerShell.auto_exclusive_zone_enable(self)\n"
        "        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)\n"
    )
    configure_with_monitor = configure_new + (
        "        monitor = _gdk_monitor()\n"
        "        if monitor is not None:\n"
        "            GtkLayerShell.set_monitor(self, monitor)\n"
    )
    if "configure_bar_layer_shell(self)" not in text:
        old_with_monitor = (
            "    def _configure_layer_shell(self) -> None:\n"
            "        GtkLayerShell.init_for_window(self)\n"
            "        GtkLayerShell.set_namespace(self, APP_ID)\n"
            "        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)\n"
            "        for edge in (\n"
            "            GtkLayerShell.Edge.TOP,\n"
            "            GtkLayerShell.Edge.LEFT,\n"
            "            GtkLayerShell.Edge.RIGHT,\n"
            "        ):\n"
            "            GtkLayerShell.set_anchor(self, edge, True)\n"
            "        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, TOP_MARGIN)\n"
            "        GtkLayerShell.auto_exclusive_zone_enable(self)\n"
            "        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)\n"
            "        monitor = _gdk_monitor()\n"
            "        if monitor is not None:\n"
            "            GtkLayerShell.set_monitor(self, monitor)\n"
        )
        old_without_monitor = (
            "    def _configure_layer_shell(self) -> None:\n"
            "        GtkLayerShell.init_for_window(self)\n"
            "        GtkLayerShell.set_namespace(self, APP_ID)\n"
            "        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)\n"
            "        for edge in (\n"
            "            GtkLayerShell.Edge.TOP,\n"
            "            GtkLayerShell.Edge.LEFT,\n"
            "            GtkLayerShell.Edge.RIGHT,\n"
            "        ):\n"
            "            GtkLayerShell.set_anchor(self, edge, True)\n"
            "        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, TOP_MARGIN)\n"
            "        GtkLayerShell.auto_exclusive_zone_enable(self)\n"
            "        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)\n"
        )
        if old_with_monitor in text:
            text = text.replace(old_with_monitor, configure_with_monitor, 1)
        elif old_without_monitor in text:
            text = text.replace(old_without_monitor, configure_new, 1)
        else:
            print(f"Aviso: se omite anclar la barra al borde configurado: {app}", flush=True)

    size_old = (
        "        self.layout = ShellLayout()\n"
        "        monitor = _gdk_monitor()\n"
        "        if monitor is not None:\n"
        "            self.layout.set_size_request(monitor.get_geometry().width, -1)\n"
        "\n"
        "        # Starfield paints the void; layout modules sit as its child above the stars.\n"
        "        self._bar_host = StarfieldBackground(\n"
        "            self.event_bus,\n"
        "            corner_radius=0.0,\n"
        "            draw_rim=True,\n"
        "        )\n"
        "        self._bar_host.get_style_context().add_class(\"shell-bar-host\")\n"
        "        self._bar_host.set_hexpand(True)\n"
        "        self._bar_host.set_halign(Gtk.Align.FILL)\n"
        "        self._bar_host.add(self.layout)\n"
        "\n"
        "        self._overlay = Gtk.Overlay()\n"
        "        self._overlay.set_hexpand(True)\n"
        "        self._overlay.set_halign(Gtk.Align.FILL)\n"
        "        if monitor is not None:\n"
        "            self._overlay.set_size_request(monitor.get_geometry().width, -1)\n"
        "        self._overlay.add(self._bar_host)\n"
        "        self.add(self._overlay)\n"
        "        if monitor is not None:\n"
        "            self.set_size_request(monitor.get_geometry().width, -1)\n"
    )
    size_new = (
        "        self.layout = ShellLayout()\n"
        "        monitor = _gdk_monitor()\n"
        "\n"
        "        # Starfield paints the void; layout modules sit as its child above the stars.\n"
        "        self._bar_host = StarfieldBackground(\n"
        "            self.event_bus,\n"
        "            corner_radius=0.0,\n"
        "            draw_rim=True,\n"
        "        )\n"
        "        self._bar_host.get_style_context().add_class(\"shell-bar-host\")\n"
        "        self._bar_host.add(self.layout)\n"
        "\n"
        "        self._overlay = Gtk.Overlay()\n"
        "        self._overlay.add(self._bar_host)\n"
        "        self.add(self._overlay)\n"
        "        for widget in (self.layout, self._bar_host, self._overlay, self):\n"
        "            apply_bar_expand_flags(widget)\n"
        "        apply_bar_size_requests(\n"
        "            (self.layout, self._overlay, self),\n"
        "            monitor,\n"
        "        )\n"
    )
    if "apply_bar_size_requests(" not in text:
        if size_old in text:
            text = text.replace(size_old, size_new, 1)
        else:
            print(f"Aviso: se omite dimensionar la barra horizontal o vertical: {app}", flush=True)

    # Drop TOP_MARGIN from imports only once nothing references it.
    if (
        "TOP_MARGIN" in text
        and "GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, TOP_MARGIN)" not in text
        and "configure_bar_layer_shell(self)" in text
    ):
        text = text.replace(
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            "    TOP_MARGIN,\n"
            ")\n",
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            ")\n",
            1,
        )

    # Final safety net for half-applied installs still referencing TOP_MARGIN.
    if (
        "set_margin(self, GtkLayerShell.Edge.TOP, TOP_MARGIN)" in text
        and "    TOP_MARGIN,\n" not in text
    ):
        broken = (
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            ")\n"
        )
        fixed = (
            "from .config import (\n"
            "    ACTIVE_THEME,\n"
            "    HYPRLAND_THEME_EXPORT_PATH,\n"
            "    PERSISTENT_WORKSPACES,\n"
            "    TOP_MARGIN,\n"
            ")\n"
        )
        if broken in text:
            text = text.replace(broken, fixed, 1)
            print(f"Aviso: se restauró TOP_MARGIN en imports rotos: {app}", flush=True)

    if text == original:
        return
    backup = app.with_suffix(app.suffix + ".aidycos-backup")
    if not backup.exists():
        shutil.copy2(app, backup)
    app.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: install.py RUTA_DE_JUGOO")
    root = Path(sys.argv[1]).expanduser().resolve()
    app = root / "shell/app.py"
    config = root / "shell/config.py"
    audio = root / "shell/servicios/audio/audio.py"
    applications = root / "shell/servicios/aplicaciones/applications.py"
    style = root / "shell/style.css"
    aidyc_helper = Path(__file__).parent / "shell/servicios/aplicaciones/aidyc_install.py"
    for path in (app, config, audio, applications, style, aidyc_helper):
        if not path.is_file():
            raise SystemExit(f"Checkout de Jugoo incompleto: falta {path}")

    install_desktop_icons(root)
    install_applications_menu(root)
    install_bar_position(root)
    # Keep the Jugoo bar visible: do not retract under maximized floating windows.
    config = root / "shell/config.py"
    config_text = config.read_text(encoding="utf-8")
    if re.search(r"^(\s*BAR_RETRACT_ENABLED\s*=\s*)True(\s*)$", config_text, re.MULTILINE):
        backup = config.with_suffix(config.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(config, backup)
        config.write_text(
            re.sub(
                r"^(\s*BAR_RETRACT_ENABLED\s*=\s*)True(\s*)$",
                r"\g<1>False\g<2>",
                config_text,
                count=1,
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
    install_battery(root)
    install_network_wifi(root)
    install_printers(root)
    install_native_workspace_dispatch(root)
    install_native_window_focus(root)
    assistant_card = root / "shell/widgets/notificaciones/assistant_card.py"
    if assistant_card.is_file():
        try_replace_once(
            assistant_card,
            "is_pointer_leaving_surface(self, event)",
            "is_pointer_leaving_surface(event)",
            "corregir compatibilidad del evento de salida del asistente",
        )

    # Do not show the Jugoo assistant card for the empty-board briefing.
    briefing = root / "shell/servicios/tareas/briefing.py"
    if briefing.is_file():
        try_replace_once(
            briefing,
            (
                "        facts = self._facts(memory=memory)\n"
                "        _briefing_diag(\n"
                '            "facts: "\n'
                '            f"empty={facts.empty} pending_today={facts.pending_today} "\n'
                '            f"overdue={facts.overdue} upcoming={facts.upcoming} "\n'
                '            f"total_open={facts.total_open} "\n'
                '            f"titles={list(facts.pending_titles) + list(facts.overdue_titles)!r} "\n'
                '            f"urgent={None if facts.most_urgent is None else facts.most_urgent.title!r}"\n'
                "        )\n"
                '        previous = facts.previous_message or "(none)"\n'
            ),
            (
                "        facts = self._facts(memory=memory)\n"
                "        _briefing_diag(\n"
                '            "facts: "\n'
                '            f"empty={facts.empty} pending_today={facts.pending_today} "\n'
                '            f"overdue={facts.overdue} upcoming={facts.upcoming} "\n'
                '            f"total_open={facts.total_open} "\n'
                '            f"titles={list(facts.pending_titles) + list(facts.overdue_titles)!r} "\n'
                '            f"urgent={None if facts.most_urgent is None else facts.most_urgent.title!r}"\n'
                "        )\n"
                "        if facts.empty:\n"
                '            _briefing_diag("skipped (empty board — no assistant card)")\n'
                '            _briefing_diag("END")\n'
                '            return "empty"\n'
                '        previous = facts.previous_message or "(none)"\n'
            ),
            "ocultar briefing vacío sin tareas",
        )

    overlay_shell = Path(__file__).parent / "shell"
    for relative in (
        # Service helpers must ship with the controller: older Jugoo branches
        # lack revealed_retract_px and the shell crashes before the bar appears.
        Path("servicios/escritorio/bar_retract.py"),
        Path("controllers/bar_retract.py"),
        Path("controllers/applications.py"),
        # Keep the modern network_bar_icon_name widget (not the old "always LAN"
        # ethernet-only indicator) so Wi-Fi shows correctly after overlay.
        Path("icons.py"),
        Path("widgets/barra/ethernet.py"),
        Path("widgets/barra/volume.py"),
        Path("widgets/audio/volume_slider.py"),
    ):
        install_overlay_file(overlay_shell / relative, root / "shell" / relative)

    try_replace_once(
        app,
        "from .widgets.barra.ethernet import EthernetWidget\n",
        "from .widgets.barra.ethernet import EthernetWidget\nfrom .widgets.barra.volume import VolumeWidget\n",
        "importar control de volumen",
    )
    app_text = app.read_text(encoding="utf-8")
    if "VolumeWidget" not in app_text:
        print(f"Aviso: el checkout no importa VolumeWidget todavía: {app}", flush=True)
    elif "self.volume_widget = VolumeWidget(" not in app_text:
        battery_anchor = "        self.battery_widget = BatteryWidget(self.event_bus, self.battery_service)\n"
        ethernet_anchor = "        self.ethernet_widget = EthernetWidget(self.event_bus, self.network_service)\n"
        if battery_anchor in app_text:
            app_text = app_text.replace(
                battery_anchor,
                battery_anchor
                + "        self.volume_widget = VolumeWidget(self.event_bus, self.audio_service)\n",
                1,
            )
        elif ethernet_anchor in app_text:
            app_text = app_text.replace(
                ethernet_anchor,
                ethernet_anchor
                + "        self.volume_widget = VolumeWidget(self.event_bus, self.audio_service)\n",
                1,
            )
        else:
            print(f"Aviso: no se pudo crear el control de volumen: {app}", flush=True)
            app_text = None
        if app_text is not None:
            backup = app.with_suffix(app.suffix + ".aidycos-backup")
            if not backup.exists():
                shutil.copy2(app, backup)
            app.write_text(app_text, encoding="utf-8")

    app_text = app.read_text(encoding="utf-8")
    if (
        "self.volume_widget = VolumeWidget(" in app_text
        and "self.layout.right.add(self.volume_widget)" not in app_text
    ):
        try_replace_once(
            app,
            "        self.layout.right.add(self.ethernet_widget)\n",
            "        self.layout.right.add(self.ethernet_widget)\n"
            "        self.layout.right.add(self.volume_widget)\n",
            "mostrar control de volumen",
        )

    applications_text = applications.read_text(encoding="utf-8")
    if "begin_aidyc_install" not in applications_text:
        try_replace_once(
            applications,
            "from .desktop import desktop_directories_stamp, scan_desktop_applications, strip_exec_field_codes\n",
            "from .aidyc_install import aidyc_is_installed, begin_aidyc_install\n"
            "from .desktop import desktop_directories_stamp, scan_desktop_applications, strip_exec_field_codes\n",
            "importar descarga de AidyC desde el dock",
        )
        try_replace_once(
            applications,
            "    def launch(self, app_id: str) -> None:\n        application = self.snapshot.app_by_id(app_id)\n",
            "    def launch(self, app_id: str) -> None:\n"
            "        ident = normalize_desktop_id(app_id)\n"
            "        if ident.casefold() == \"aidyc\" and not aidyc_is_installed():\n"
            "            begin_aidyc_install()\n"
            "            return\n"
            "        application = self.snapshot.app_by_id(app_id)\n",
            "descargar AidyC al pulsar su icono si no está instalado",
        )
    try_replace_once(
        applications,
        "            self._pinned_ids, self._favorite_ids = load_application_prefs(self._path)\n",
        "            self._pinned_ids, self._favorite_ids = load_application_prefs(self._path)\n"
        "            if not self._path.exists():\n"
        "                self._pinned_ids = (\"aidyc\",)\n"
        "                self._persist()\n",
        "mostrar AidyC en el dock de una instalación nueva",
    )
    installed_helper = root / "shell/servicios/aplicaciones/aidyc_install.py"
    # Never overwrite a newer helper already present in the Jugoo checkout.
    if not installed_helper.exists():
        installed_helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(aidyc_helper, installed_helper)

    install_system_volume_read_fallback(audio)

    if "def set_system_volume(" not in audio.read_text(encoding="utf-8"):
        audio_methods = '''\n    def set_system_volume(self, volume: float) -> None:\n        """Set default sink volume from the top-bar control."""\n        clamped = max(0.0, min(1.0, float(volume)))\n        percent = f"{int(round(clamped * 100))}%"\n\n        def apply() -> None:\n            ok = self._run_command(["pactl", "set-sink-volume", "@DEFAULT_SINK@", percent])\n            if not ok:\n                ok = self._run_command(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", str(clamped)])\n            if ok and not self._stop_event.is_set():\n                self._refresh_audio()\n\n        self._start_operation("audio-set-system-volume", apply)\n\n    def toggle_system_mute(self) -> None:\n        """Toggle mute on the default sink."""\n        def apply() -> None:\n            ok = self._run_command(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])\n            if not ok:\n                ok = self._run_command(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])\n            if ok and not self._stop_event.is_set():\n                self._refresh_audio()\n\n        self._start_operation("audio-toggle-system-mute", apply)\n'''
        audio_marker = "    def toggle_stream_mute(self, stream_id: str) -> None:\n"
        try_replace_once(
            audio,
            audio_marker,
            audio_methods + "\n" + audio_marker,
            "operaciones de volumen global",
        )

    css = '''\nbox.volume-widget { margin: 0 2px; }\nbox.volume-widget button.volume-mute-button {\n    padding: 0; min-width: 0; min-height: 0; background: transparent;\n    border: none; box-shadow: none; color: @shell_text_primary;\n}\nbox.volume-widget box.volume-slider { min-width: 72px; }\n'''
    css_anchor = "box.volume-slider {\n"
    style_text = style.read_text(encoding="utf-8")
    if "box.volume-widget {" not in style_text:
        if css_anchor not in style_text:
            print(f"Aviso: no se pudo aplicar el estilo del volumen: {style}", flush=True)
        else:
            backup = style.with_suffix(style.suffix + ".aidycos-backup")
            if not backup.exists():
                shutil.copy2(style, backup)
            style.write_text(style_text.replace(css_anchor, css + "\n" + css_anchor, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
