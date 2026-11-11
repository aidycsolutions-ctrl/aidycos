#!/usr/bin/env python3
"""Apply the small local Jugoo additions used by the AidyCOS desktop profile."""

from __future__ import annotations

import shutil
import sys
import re
from pathlib import Path


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
    if "TITLE_DESKTOP" not in identity.read_text(encoding="utf-8"):
        replace_once(
            identity,
            "TITLE_PINNED_OVERFLOW = f\"{APPLICATION_NAME} Pinned Overflow\"\n",
            "TITLE_PINNED_OVERFLOW = f\"{APPLICATION_NAME} Pinned Overflow\"\n"
            "TITLE_DESKTOP = f\"{APPLICATION_NAME} Desktop Icons\"\n",
            "identificar la capa de iconos del escritorio",
        )

    config = root / "shell/config.py"
    config_text = config.read_text(encoding="utf-8")
    if "DESKTOP_ICONS_ENABLED" not in config_text:
        config_text = config_text.rstrip() + (
            "\n\n# AidyCOS: escritorio con accesos directos habilitados.\n"
            "DESKTOP_ICONS_ENABLED = True\n"
            "DESKTOP_ICONS_PATH = \"desktop-icons.json\"\n"
            "DESKTOP_ICON_SIZE = 48\n"
            "DESKTOP_ICON_LABEL_WIDTH = 96\n"
            "DESKTOP_ICON_CELL_WIDTH = 104\n"
            "DESKTOP_ICON_CELL_HEIGHT = 96\n"
            "DESKTOP_ICON_DRAG_THRESHOLD_PX = 6\n"
        )
    else:
        config_text = re.sub(
            r"^(\s*DESKTOP_ICONS_ENABLED\s*=\s*)False(\s*)$",
            r"\g<1>True\g<2>",
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
            '        "Gestionar impresoras CUPS y abrir el gestor del sistema.",\n'
            "    ),\n"
            '    CategoryId.AVANZADO: ("Avanzado", "Rendimiento e integraciones"),\n',
            "añadir metadatos de Impresoras",
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
    install_printers(root)
    install_native_workspace_dispatch(root)
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
