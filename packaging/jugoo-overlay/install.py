#!/usr/bin/env python3
"""Apply the small local Jugoo additions used by the AidyCOS desktop profile."""

from __future__ import annotations

import shutil
import sys
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

    config_text = config.read_text(encoding="utf-8")
    if "DESKTOP_ICONS_ENABLED = True" not in config_text:
        replace_once(
            config,
            "DESKTOP_ICONS_ENABLED = False",
            "DESKTOP_ICONS_ENABLED = True",
            "mostrar iconos del escritorio por defecto",
        )
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
