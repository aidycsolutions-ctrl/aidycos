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
    replace_once(
        runtime_paths,
        "from .config import CLIPBOARD_HISTORY_PATH, CLIPBOARD_IMAGES_DIR, PINNED_APPS_PATH, TASKS_PATH\n",
        "from .config import CLIPBOARD_HISTORY_PATH, CLIPBOARD_IMAGES_DIR, PINNED_APPS_PATH, TASKS_PATH, DESKTOP_ICONS_PATH\n",
        "importar la ruta de iconos del escritorio",
    )
    replace_once(
        runtime_paths,
        "def tasks_path() -> Path:\n",
        "def desktop_icons_path() -> Path:\n"
        "    return xdg_data_dir() / DESKTOP_ICONS_PATH\n\n\n"
        "def tasks_path() -> Path:\n",
        "definir almacenamiento de iconos del escritorio",
    )
    identity = root / "shell/identity.py"
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
    if "def _desktop_icons_editor(" not in pages.read_text(encoding="utf-8"):
        with pages.open("a", encoding="utf-8") as stream:
            stream.write("\n\n" + editor.rstrip() + "\n")


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

    replace_once(
        app,
        "from .widgets.barra.ethernet import EthernetWidget\n",
        "from .widgets.barra.ethernet import EthernetWidget\nfrom .widgets.barra.volume import VolumeWidget\n",
        "importar control de volumen",
    )
    replace_once(
        app,
        "        self.battery_widget = BatteryWidget(self.event_bus, self.battery_service)\n",
        "        self.battery_widget = BatteryWidget(self.event_bus, self.battery_service)\n"
        "        self.volume_widget = VolumeWidget(self.event_bus, self.audio_service)\n",
        "crear control de volumen",
    )
    replace_once(
        app,
        "        self.layout.right.add(self.ethernet_widget)\n",
        "        self.layout.right.add(self.ethernet_widget)\n"
        "        self.layout.right.add(self.volume_widget)\n",
        "mostrar control de volumen",
    )

    replace_once(
        applications,
        "from .desktop import desktop_directories_stamp, scan_desktop_applications, strip_exec_field_codes\n",
        "from .aidyc_install import aidyc_is_installed, begin_aidyc_install\n"
        "from .desktop import desktop_directories_stamp, scan_desktop_applications, strip_exec_field_codes\n",
        "importar descarga de AidyC desde el dock",
    )
    replace_once(
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
    replace_once(
        applications,
        "            self._pinned_ids, self._favorite_ids = load_application_prefs(self._path)\n",
        "            self._pinned_ids, self._favorite_ids = load_application_prefs(self._path)\n"
        "            if not self._path.exists():\n"
        "                self._pinned_ids = (\"aidyc\",)\n"
        "                self._persist()\n",
        "mostrar AidyC en el dock de una instalación nueva",
    )
    installed_helper = root / "shell/servicios/aplicaciones/aidyc_install.py"
    if not installed_helper.exists() or installed_helper.read_bytes() != aidyc_helper.read_bytes():
        if installed_helper.exists():
            backup = installed_helper.with_suffix(".py.aidycos-backup")
            if not backup.exists():
                shutil.copy2(installed_helper, backup)
        installed_helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(aidyc_helper, installed_helper)

    audio_methods = '''\n    def set_system_volume(self, volume: float) -> None:\n        """Set default sink volume from the top-bar control."""\n        clamped = max(0.0, min(1.0, float(volume)))\n        percent = f"{int(round(clamped * 100))}%"\n\n        def apply() -> None:\n            ok = self._run_command(["pactl", "set-sink-volume", "@DEFAULT_SINK@", percent])\n            if not ok:\n                ok = self._run_command(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", str(clamped)])\n            if ok and not self._stop_event.is_set():\n                self._refresh_audio()\n\n        self._start_operation("audio-set-system-volume", apply)\n\n    def toggle_system_mute(self) -> None:\n        """Toggle mute on the default sink."""\n        def apply() -> None:\n            ok = self._run_command(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])\n            if not ok:\n                ok = self._run_command(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])\n            if ok and not self._stop_event.is_set():\n                self._refresh_audio()\n\n        self._start_operation("audio-toggle-system-mute", apply)\n'''
    audio_marker = "    def toggle_stream_mute(self, stream_id: str) -> None:\n"
    replace_once(audio, audio_marker, audio_methods + "\n" + audio_marker,
                 "operaciones de volumen global")

    css = '''\nbox.volume-widget { margin: 0 2px; }\nbox.volume-widget button.volume-mute-button {\n    padding: 0; min-width: 0; min-height: 0; background: transparent;\n    border: none; box-shadow: none; color: @shell_text_primary;\n}\nbox.volume-widget box.volume-slider { min-width: 72px; }\n'''
    css_anchor = "box.volume-slider {\n"
    if "box.volume-widget {" not in style.read_text(encoding="utf-8"):
        text = style.read_text(encoding="utf-8")
        if css_anchor not in text:
            raise SystemExit(f"No se pudo aplicar el estilo del volumen: {style}")
        backup = style.with_suffix(style.suffix + ".aidycos-backup")
        if not backup.exists():
            shutil.copy2(style, backup)
        style.write_text(text.replace(css_anchor, css + "\n" + css_anchor, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
