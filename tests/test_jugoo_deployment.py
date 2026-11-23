from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deploy_jugoo", ROOT / "scripts" / "deploy-jugoo.py"
)
assert SPEC and SPEC.loader
deploy_jugoo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_jugoo)


def make_source(path: Path, value: str) -> Path:
    shell = path / "shell"
    shell.mkdir(parents=True)
    (shell / "__main__.py").write_text(value, encoding="utf-8")
    return path


class JugooDeploymentTests(unittest.TestCase):
    def test_new_install_preserves_existing_user_checkout_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_source(root / "official", "official v1")
            destination = root / "opt" / "aidyc" / "jugoo"
            user_checkout = root / ".config" / "jugoo"
            user_checkout.mkdir(parents=True)
            (user_checkout / "local-change.py").write_text("keep me", encoding="utf-8")

            deploy_jugoo.deploy(source, destination)

            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v1")
            self.assertTrue((destination / deploy_jugoo.MARKER).is_file())
            self.assertEqual((user_checkout / "local-change.py").read_text(), "keep me")
            self.assertFalse(destination.with_name("jugoo.aidycos-preserved").exists())

    def test_existing_iso_install_is_preserved_and_managed_install_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "opt" / "aidyc" / "jugoo"
            destination.mkdir(parents=True)
            (destination / "iso-version.txt").write_text("ISO copy", encoding="utf-8")
            source_v1 = make_source(root / "source-v1", "official v1")

            deploy_jugoo.deploy(source_v1, destination)

            preserved = destination.with_name("jugoo.aidycos-preserved")
            self.assertEqual((preserved / "iso-version.txt").read_text(), "ISO copy")
            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v1")

            source_v2 = make_source(root / "source-v2", "official v2")
            deploy_jugoo.deploy(source_v2, destination)

            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v2")
            self.assertEqual((preserved / "iso-version.txt").read_text(), "ISO copy")

    def test_private_clone_and_opt_stay_readable_by_the_desktop_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_source(root / "official", "official v1")
            source.chmod(0o700)
            (source / "shell").chmod(0o700)
            parent = root / "opt" / "aidyc"
            parent.mkdir(parents=True)
            parent.chmod(0o700)
            destination = parent / "jugoo"

            deploy_jugoo.deploy(source, destination)

            self.assertEqual(destination.stat().st_mode & 0o005, 0o005)
            self.assertEqual((destination / "shell").stat().st_mode & 0o005, 0o005)
            self.assertEqual(
                (destination / "shell" / "__main__.py").stat().st_mode & 0o004,
                0o004,
            )
            self.assertEqual(parent.stat().st_mode & 0o005, 0o005)

    def test_launcher_and_user_service_override_share_system_entry_point(self) -> None:
        launcher = (ROOT / "packaging" / "jugoo-launcher").read_text(encoding="utf-8")
        service = (
            ROOT
            / "packaging"
            / "systemd"
            / "jugoo-task-watcher.service.d"
            / "aidycos.conf"
        ).read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install-debian-profile.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("OPT_JUGOO=/opt/aidyc/jugoo", launcher)
        self.assertIn("python3 -m shell \"$@\"", launcher)
        self.assertIn("ExecStart=/usr/local/bin/jugoo --task-watcher", service)
        self.assertIn("exec-once = /usr/local/bin/jugoo", installer)
        self.assertIn("feature/atajos-aidyc-escritorio", installer)
        self.assertLess(
            installer.index('sudo chmod -R a+rX "${jugoo_dir}"'),
            installer.index('(cd "${jugoo_dir}" && python3 -m shell --install)'),
        )
        self.assertIn("seed-desktop-defaults.py", installer)
        self.assertIn("bind = ALT, F4, exec, jugoo action session", installer)
        self.assertIn("bind = SUPER, SPACE, exec, jugoo action launcher", installer)
        self.assertIn("bind = SUPER, E, exec, /usr/bin/env GDK_BACKEND=wayland /usr/bin/thunar", installer)
        self.assertIn("aidycos-download-dir", installer)
        self.assertIn("exec-once = /usr/local/bin/aidycos-download-dir ensure", installer)
        self.assertIn("exec-once = /usr/local/bin/aidycos-download-dir watch", installer)
        # Duplicate Super+Space (hyprland.conf + aidycos.conf) toggles twice → no-op.
        self.assertIn("Super+Space launcher duplicado eliminado", installer)
        self.assertIn("org.freedesktop.ibus.general.hotkey triggers", installer)
        self.assertNotIn("bind = CTRL, SPACE, exec, jugoo action launcher", installer)
        self.assertNotIn("bind = CTRL, E, exec, /usr/bin/env GDK_BACKEND=wayland /usr/bin/thunar", installer)
        self.assertIn("aidycos-impresoras.desktop", installer)
        self.assertIn("aidycos-paquetes.desktop", installer)
        self.assertIn("aidycos-onlyoffice.desktop", installer)
        self.assertIn("aidycos-onlyoffice", installer)
        self.assertIn("hyprpolkitagent", installer)
        self.assertIn("DESKTOP_ICONS_ENABLED = False", (
            ROOT / "packaging" / "jugoo-overlay" / "install.py"
        ).read_text(encoding="utf-8"))

    def test_restart_does_not_reload_hyprland_when_theme_is_unchanged(self) -> None:
        boot = (
            ROOT / "packaging" / "jugoo-overlay" / "patches" / "jugoo_aidycos_boot.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _apply_theme_reload_guard", boot)
        self.assertIn("if path.read_text(encoding=\"utf-8\") == previous:", boot)
        self.assertIn("_apply_theme_reload_guard()", boot)
        self.assertIn("def _apply_active_window_icons", boot)
        self.assertIn('"prev": "media-skip-backward"', boot)
        self.assertIn("def _apply_workspace_icon_files", boot)
        self.assertIn("def _apply_quiet_relaunch", boot)
        relaunch = (
            ROOT / "packaging" / "jugoo-overlay" / "shell" / "runtime_relaunch.py"
        ).read_text(encoding="utf-8")
        self.assertIn("sleep 0.45", relaunch)
        self.assertIn("os._exit(0)", relaunch)
        self.assertNotIn("os.execv(", relaunch)

        spec = importlib.util.spec_from_file_location(
            "jugoo_overlay_install_theme",
            ROOT / "packaging" / "jugoo-overlay" / "install.py",
        )
        assert spec and spec.loader
        overlay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overlay)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            theme = root / "shell" / "ui" / "theme.py"
            theme.parent.mkdir(parents=True)
            theme.write_text(
                "        try:\n"
                "            export_hypr_theme(theme, self._hypr_export_path)\n"
                "            self._reload_hyprland()\n"
                "        except (OSError, subprocess.SubprocessError) as error:\n"
                "            print(f\"Jugoo theme: Hyprland export skipped: {error}\")\n",
                encoding="utf-8",
            )
            overlay.install_quiet_theme_reload(root)
            text = theme.read_text(encoding="utf-8")
            self.assertIn("if self._hypr_export_path.read_text(encoding=\"utf-8\") == previous:", text)
            self.assertLess(text.index("== previous"), text.index("self._reload_hyprland()"))
            overlay.install_quiet_theme_reload(root)
            self.assertEqual(text, theme.read_text(encoding="utf-8"))

    def test_overlay_keeps_desktop_layer_transparent(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "jugoo_overlay_install",
            ROOT / "packaging" / "jugoo-overlay" / "install.py",
        )
        assert spec and spec.loader
        overlay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overlay)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            style = root / "shell" / "style.css"
            style.parent.mkdir(parents=True)
            style.write_text("/* base */\n", encoding="utf-8")
            overlay.ensure_desktop_icons_css(root)
            text = style.read_text(encoding="utf-8")
            self.assertIn("window#shell-desktop.desktop-layer", text)
            self.assertIn("background-color: transparent", text)
            # Idempotent.
            overlay.ensure_desktop_icons_css(root)
            self.assertEqual(text, style.read_text(encoding="utf-8"))

    def test_overlay_adds_applications_menu_button(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "jugoo_overlay_install",
            ROOT / "packaging" / "jugoo-overlay" / "install.py",
        )
        assert spec and spec.loader
        overlay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overlay)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "shell" / "app.py"
            layout = root / "shell" / "settings" / "layout_model.py"
            style = root / "shell" / "style.css"
            app.parent.mkdir(parents=True)
            layout.parent.mkdir(parents=True)
            app.write_text(
                "from .widgets.barra.pinned_apps import PinnedAppsWidget\n"
                "class Shell:\n"
                "    def build(self):\n"
                "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n"
                "        self.layout.left.add(self.pinned_apps_widget)\n",
                encoding="utf-8",
            )
            layout.write_text(
                'DEFAULT_LAYOUT = (\n'
                '    ModuleSlot("pinned_apps", "left", 1),\n'
                '    ModuleSlot("keyboard_cat", "left", 2),\n'
                ')\n',
                encoding="utf-8",
            )
            style.write_text("/* base */\n", encoding="utf-8")
            overlay.install_applications_menu(root)
            app_text = app.read_text(encoding="utf-8")
            self.assertIn("ApplicationsMenuWidget", app_text)
            self.assertIn("self.layout.left.add(self.applications_menu_widget)", app_text)
            self.assertIn("self.layout.left.add(self.pinned_apps_widget)", app_text)
            self.assertLess(
                app_text.index("self.layout.left.add(self.applications_menu_widget)"),
                app_text.index("self.layout.left.add(self.pinned_apps_widget)"),
            )
            layout_text = layout.read_text(encoding="utf-8")
            self.assertIn("applications_menu", layout_text)
            self.assertIn("pinned_apps", layout_text)
            self.assertIn("applications-menu-button", style.read_text(encoding="utf-8"))
            self.assertTrue((root / "shell/widgets/barra/applications.py").is_file())
            self.assertEqual(app_text.count("self.layout.left.add(self.applications_menu_widget)"), 1)

            # Hostname between the button and the dock must not add a second grid.
            app.write_text(
                app_text.replace(
                    "        self.layout.left.add(self.applications_menu_widget)\n"
                    "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n",
                    "        self.layout.left.add(self.applications_menu_widget)\n"
                    "        self.host_identity_widget = HostIdentityWidget()\n"
                    "        self.layout.left.add(self.host_identity_widget)\n"
                    "        self.applications_menu_widget = ApplicationsMenuWidget(self.toggle_launcher)\n"
                    "        self.layout.left.add(self.applications_menu_widget)\n"
                    "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n",
                    1,
                ),
                encoding="utf-8",
            )
            overlay.install_applications_menu(root)
            repaired = app.read_text(encoding="utf-8")
            self.assertEqual(repaired.count("self.layout.left.add(self.applications_menu_widget)"), 1)
            self.assertIn("self.host_identity_widget = HostIdentityWidget()", repaired)
            self.assertLess(
                repaired.index("self.layout.left.add(self.applications_menu_widget)"),
                repaired.index("self.layout.left.add(self.host_identity_widget)"),
            )
            self.assertLess(
                repaired.index("self.layout.left.add(self.host_identity_widget)"),
                repaired.index("self.layout.left.add(self.pinned_apps_widget)"),
            )
