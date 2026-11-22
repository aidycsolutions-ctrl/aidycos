"""Minimize/focus helpers for floating Hyprland windows."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parents[1] / "packaging" / "hyprland" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("aidycos_ventanas", _SCRIPTS / "ventanas.py")
ventanas = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(ventanas)


def _window(
    address: str,
    *,
    focus: int = 0,
    workspace: str = "1",
    workspace_id: int = 1,
    mapped: bool = True,
    hidden: bool = False,
    class_name: str = "foot",
    title: str = "term",
) -> dict:
    return {
        "address": address,
        "focusHistoryID": focus,
        "workspace": {"id": workspace_id, "name": workspace},
        "mapped": mapped,
        "hidden": hidden,
        "class": class_name,
        "title": title,
        "at": [10, 10],
        "size": [400, 300],
        "floating": True,
        "pinned": False,
        "fullscreen": 0,
        "monitor": 0,
    }


class MinimizeFocusTests(unittest.TestCase):
    def test_find_window_skips_minimized_active(self) -> None:
        minimized = _window("0xmin", workspace="special:minimizados", workspace_id=-98, focus=0)
        visible = _window("0xvis", focus=1)

        def fake_query(name: str):
            if name == "activewindow":
                return minimized
            if name == "clients":
                return [minimized, visible]
            if name == "cursorpos":
                return {"x": 0, "y": 0}
            raise AssertionError(name)

        with (
            mock.patch.object(ventanas, "query", side_effect=fake_query),
            mock.patch.object(ventanas, "window_bar_height", return_value=0),
        ):
            self.assertEqual(ventanas.find_window(None)["address"], "0xvis")

    def test_find_window_prefers_titlebar_hit(self) -> None:
        other = _window("0xother", focus=0)
        other["at"] = [0, 100]
        other["size"] = [400, 300]
        target = _window("0xtarget", focus=1)
        target["at"] = [500, 100]
        target["size"] = [400, 300]

        def fake_query(name: str):
            if name == "cursorpos":
                # Inside hyprbars strip of target (bar_height=28 → y in [72, 100)).
                return {"x": 700, "y": 80}
            if name == "activewindow":
                return other
            if name == "clients":
                return [other, target]
            raise AssertionError(name)

        with (
            mock.patch.object(ventanas, "query", side_effect=fake_query),
            mock.patch.object(ventanas, "window_bar_height", return_value=28),
        ):
            self.assertEqual(ventanas.find_window(None)["address"], "0xtarget")

    def test_find_window_unknown_address_uses_titlebar(self) -> None:
        target = _window("0xoffice", focus=0)
        target["at"] = [100, 80]
        target["size"] = [800, 600]

        def fake_query(name: str):
            if name == "cursorpos":
                return {"x": 200, "y": 60}
            if name == "clients":
                return [target]
            raise AssertionError(name)

        with (
            mock.patch.object(ventanas, "query", side_effect=fake_query),
            mock.patch.object(ventanas, "window_bar_height", return_value=28),
        ):
            self.assertEqual(ventanas.find_window("0xdead")["address"], "0xoffice")

    def test_find_window_falls_back_when_active_is_empty(self) -> None:
        recent = _window("0xabc", focus=0)
        other = _window("0xdef", focus=1)
        with mock.patch.object(
            ventanas,
            "query",
            side_effect=lambda name: (
                {"address": ""}
                if name == "activewindow"
                else [recent, other]
            ),
        ):
            found = ventanas.find_window(None)
        self.assertEqual(found["address"], "0xabc")

    def test_effectively_focused_when_layer_bar_stole_focus(self) -> None:
        recent = _window("0xabc", focus=0)
        other = _window("0xdef", focus=1)
        with mock.patch.object(
            ventanas,
            "query",
            side_effect=lambda name: (
                {"address": ""}
                if name == "activewindow"
                else [recent, other]
            ),
        ):
            self.assertTrue(ventanas.is_effectively_focused(recent, {"address": ""}))
            self.assertFalse(ventanas.is_effectively_focused(other, {"address": ""}))

    def test_effectively_focused_false_when_another_client_is_active(self) -> None:
        recent = _window("0xabc", focus=1)
        other = _window("0xdef", focus=0)
        with mock.patch.object(
            ventanas,
            "query",
            side_effect=lambda name: [recent, other] if name == "clients" else {},
        ):
            self.assertFalse(ventanas.is_effectively_focused(recent, other))
            self.assertTrue(ventanas.is_effectively_focused(other, other))

    def test_cmd_focus_minimizes_after_bar_steals_focus(self) -> None:
        recent = _window("0xabc", focus=0)
        calls: list[tuple] = []

        def fake_query(name: str):
            if name == "activewindow":
                return {"address": ""}
            if name == "activeworkspace":
                return {"id": 1, "name": "1"}
            if name == "clients":
                return [recent]
            if name == "monitors":
                return [{"specialWorkspace": {"id": 0, "name": ""}}]
            return {}

        with (
            mock.patch.object(ventanas, "query", side_effect=fake_query),
            mock.patch.object(ventanas, "load_state", return_value={"snaps": {}, "minimized": []}),
            mock.patch.object(ventanas, "save_state"),
            mock.patch.object(ventanas, "dispatch", side_effect=lambda *args: calls.append(args)),
        ):
            ventanas.cmd_focus("0xabc")

        self.assertTrue(calls)
        self.assertTrue(
            any(
                any(str(part).startswith("movetoworkspacesilent special:minimizados") for part in group)
                for group in calls
            )
        )

    def test_alt_tab_candidates_stay_on_active_desktop(self) -> None:
        here = _window("0xaaa", workspace="1", workspace_id=1)
        other = _window("0xbbb", workspace="2", workspace_id=2)
        with mock.patch.object(
            ventanas,
            "query",
            side_effect=lambda name: (
                {"id": 1, "name": "1"}
                if name == "activeworkspace"
                else [here, other]
            ),
        ):
            candidates = ventanas._alt_tab_candidates()
        self.assertEqual([window["address"] for window in candidates], ["0xaaa"])

    def test_cmd_alt_tab_does_not_switch_workspace(self) -> None:
        first = _window("0xaaa", workspace="1", workspace_id=1)
        second = _window("0xbbb", workspace="1", workspace_id=1)
        requests: list[str] = []

        def fake_query(name: str):
            if name == "activewindow":
                return {"address": "0xaaa"}
            if name == "activeworkspace":
                return {"id": 1, "name": "1"}
            if name == "clients":
                return [first, second]
            return {}

        with (
            mock.patch.object(ventanas, "query", side_effect=fake_query),
            mock.patch.object(ventanas, "request", side_effect=lambda cmd: requests.append(cmd)),
            mock.patch.object(ventanas, "dispatch", side_effect=AssertionError("alt-tab must not batch")),
        ):
            ventanas.cmd_alt_tab()

        joined = "\n".join(requests)
        self.assertIn("dispatch focuswindow address:0xbbb", joined)
        self.assertIn("dispatch bringactivetotop", joined)
        self.assertIn("dispatch alterzorder top,address:0xbbb", joined)
        self.assertNotIn("workspace", joined)
        # Raise must run after focus as a separate request (not one [[BATCH]]).
        focus_i = next(i for i, cmd in enumerate(requests) if "focuswindow address:0xbbb" in cmd)
        bring_i = next(i for i, cmd in enumerate(requests) if cmd == "dispatch bringactivetotop")
        self.assertLess(focus_i, bring_i)


class AidyCFullscreenTests(unittest.TestCase):
    def test_is_aidyc_window_matches_class_not_chat(self) -> None:
        self.assertTrue(ventanas.is_aidyc_window(_window("0x1", class_name="aidyc", title="AidyC")))
        self.assertTrue(ventanas.is_aidyc_window(_window("0x2", class_name="AidyC", title="AidyC")))
        self.assertFalse(ventanas.is_aidyc_window(_window("0x3", class_name="aidychat", title="AidyChat")))
        self.assertFalse(ventanas.is_aidyc_window(_window("0x4", class_name="aidycai", title="AIDYCAI")))
        chrome = _window(
            "0xch",
            class_name="google-chrome",
            title="AidyC Solution — Gestión empresarial integral - Google Chrome",
        )
        self.assertFalse(ventanas.is_aidyc_window(chrome))

    def test_is_aidyc_window_matches_title_when_class_unbranded(self) -> None:
        self.assertTrue(ventanas.is_aidyc_window(_window("0x5", class_name="Tk", title="AidyC 33.3")))
        self.assertFalse(ventanas.is_aidyc_window(_window("0x6", class_name="Tk", title="AidyChat")))
        self.assertFalse(
            ventanas.is_aidyc_window(_window("0x7", class_name="Tk", title="AidyC Solution"))
        )

    def test_bienvenido_is_login_not_fullscreen(self) -> None:
        welcome = _window("0xw", class_name="Tk", title="AidyC 33.4 Bienvenido Minion")
        welcome["size"] = [1280, 800]
        self.assertTrue(ventanas.is_aidyc_window(welcome))
        self.assertTrue(ventanas.is_aidyc_login_window(welcome))
        with (
            mock.patch.object(ventanas, "sync_titlebars"),
            mock.patch.object(ventanas, "find_window", return_value=welcome),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "present_aidyc_window", side_effect=AssertionError("no fs")),
            mock.patch.object(ventanas, "clamp_title_visible", side_effect=AssertionError("no clamp")),
            mock.patch.object(ventanas, "_schedule_aidyc_followup") as follow,
        ):
            ventanas.on_open_window("0xw")
        follow.assert_called_once_with("0xw")

    def test_on_open_window_presents_aidyc_only(self) -> None:
        aidyc = _window("0xaidyc", class_name="aidyc", title="AidyC")
        aidyc["at"] = [0, 0]
        aidyc["size"] = [1920, 1080]
        firefox = _window("0xff", class_name="firefox-esr", title="Mozilla Firefox")

        with (
            mock.patch.object(ventanas, "sync_titlebars"),
            mock.patch.object(ventanas, "find_window", return_value=aidyc),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "present_aidyc_window") as present,
            mock.patch.object(ventanas, "_schedule_aidyc_followup") as follow,
            mock.patch.object(ventanas, "fit_to_work_area", side_effect=AssertionError("no work-area")),
        ):
            ventanas.on_open_window("0xaidyc")
        present.assert_called_once_with(aidyc)
        follow.assert_called_once_with("0xaidyc")

        with (
            mock.patch.object(ventanas, "sync_titlebars"),
            mock.patch.object(ventanas, "find_window", return_value=firefox),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "covers_shell_bar", return_value=False),
            mock.patch.object(ventanas, "fit_to_work_area") as fit,
            mock.patch.object(ventanas, "clamp_title_visible") as clamp,
            mock.patch.object(ventanas, "present_aidyc_window", side_effect=AssertionError("no fs")),
        ):
            ventanas.on_open_window("0xff")
        fit.assert_called_once_with(firefox)
        clamp.assert_not_called()

        thunar = _window("0xth", class_name="thunar", title="Home")
        with (
            mock.patch.object(ventanas, "sync_titlebars"),
            mock.patch.object(ventanas, "find_window", return_value=thunar),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "covers_shell_bar", return_value=False),
            mock.patch.object(ventanas, "fit_to_work_area", side_effect=AssertionError("no auto-max")),
            mock.patch.object(ventanas, "clamp_title_visible") as clamp,
            mock.patch.object(ventanas, "present_aidyc_window", side_effect=AssertionError("no fs")),
        ):
            ventanas.on_open_window("0xth")
        clamp.assert_called_once_with(thunar)

    def test_login_window_is_not_force_fullscreen(self) -> None:
        login = _window("0xlogin", class_name="Tk", title="AidyC Login")
        login["size"] = [480, 360]
        self.assertTrue(ventanas.is_aidyc_login_window(login))
        with (
            mock.patch.object(ventanas, "sync_titlebars"),
            mock.patch.object(ventanas, "find_window", return_value=login),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "present_aidyc_window", side_effect=AssertionError("no fs")),
            mock.patch.object(ventanas, "clamp_title_visible", side_effect=AssertionError("no clamp")),
            mock.patch.object(ventanas, "_schedule_aidyc_followup") as follow,
        ):
            ventanas.on_open_window("0xlogin")
        follow.assert_called_once_with("0xlogin")

    def test_reveal_upgrades_maximized_aidyc(self) -> None:
        aidyc = _window("0xaidyc", class_name="aidyc", title="AidyC")
        aidyc["fullscreen"] = 1
        aidyc["at"] = [0, 57]
        aidyc["size"] = [1920, 1023]
        with (
            mock.patch.object(ventanas, "query", return_value=[aidyc]),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "covers_shell_bar", return_value=True),
            mock.patch.object(ventanas, "present_aidyc_window") as present,
            mock.patch.object(ventanas, "fit_to_work_area", side_effect=AssertionError("no snap")),
        ):
            ventanas.reveal_covered_windows()
        present.assert_called_once_with(aidyc)

    def test_reveal_skips_fullscreen_aidyc(self) -> None:
        aidyc = _window("0xaidyc", class_name="aidyc", title="AidyC")
        aidyc["fullscreen"] = 3
        aidyc["at"] = [0, 0]
        aidyc["size"] = [1920, 1080]
        with (
            mock.patch.object(ventanas, "query", return_value=[aidyc]),
            mock.patch.object(ventanas, "is_managed", return_value=True),
            mock.patch.object(ventanas, "fit_to_work_area", side_effect=AssertionError("no snap")),
            mock.patch.object(ventanas, "present_aidyc_window", side_effect=AssertionError("no present")),
            mock.patch.object(ventanas, "clamp_title_visible", side_effect=AssertionError("no clamp")),
        ):
            ventanas.reveal_covered_windows()

    def test_is_true_fullscreen_modes(self) -> None:
        maximized = _window("0xmax", class_name="foot")
        maximized["fullscreen"] = 1
        maximized["at"] = [0, 57]
        maximized["size"] = [1920, 1023]
        covered = _window("0xfull", class_name="aidyc", title="AidyC")
        covered["fullscreen"] = 3
        covered["at"] = [0, 0]
        covered["size"] = [1920, 1080]
        with mock.patch.object(
            ventanas,
            "monitor_by_id",
            return_value={"x": 0, "y": 0, "width": 1920, "height": 1080, "reserved": [0, 57, 0, 0]},
        ):
            self.assertFalse(ventanas.is_true_fullscreen(maximized))
            self.assertTrue(ventanas.is_true_fullscreen(covered))

    def test_present_aidyc_focuses_separately(self) -> None:
        aidyc = _window("0xaidyc", class_name="aidyc", title="AidyC")
        aidyc["at"] = [0, 0]
        aidyc["size"] = [1920, 1080]
        requests: list[str] = []
        focused = {"n": 0}

        def fake_request(cmd: str) -> str:
            requests.append(cmd)
            return "ok"

        with (
            mock.patch.object(ventanas, "request", side_effect=fake_request),
            mock.patch.object(ventanas, "is_true_fullscreen", side_effect=[False, True]),
            mock.patch.object(ventanas, "find_window", return_value=aidyc),
            mock.patch.object(ventanas, "focus_and_raise", side_effect=lambda _a: focused.__setitem__("n", focused["n"] + 1)),
            mock.patch.object(ventanas, "query", return_value=[aidyc]),
        ):
            ventanas.present_aidyc_window(aidyc)
        self.assertIn("dispatch focuswindow address:0xaidyc", requests)
        self.assertIn("dispatch fullscreenstate 3 3", requests)
        self.assertGreaterEqual(focused["n"], 1)


class ZoneRectTests(unittest.TestCase):
    def test_max_has_no_outer_gap(self) -> None:
        area = (0, 57, 1920, 1023)
        self.assertEqual(ventanas.zone_rect("max", area), area)

    def test_halves_flush_outer_edges(self) -> None:
        area = (0, 57, 1920, 1023)
        left = ventanas.zone_rect("left", area)
        right = ventanas.zone_rect("right", area)
        self.assertEqual(left[0], 0)
        self.assertEqual(left[1], 57)
        self.assertEqual(left[3], 1023)
        self.assertEqual(right[0] + right[2], 1920)
        self.assertEqual(right[1] + right[3], 57 + 1023)
        self.assertEqual(right[0] - (left[0] + left[2]), ventanas.GAP)

    def test_chrome_auto_max_class(self) -> None:
        self.assertTrue(ventanas._AUTO_MAX_CLASS.match("google-chrome"))
        self.assertTrue(ventanas._AUTO_MAX_CLASS.match("thunar"))
        self.assertTrue(ventanas._AUTO_MAX_CLASS.match("firefox"))


class CoversShellBarTests(unittest.TestCase):
    def test_mode1_maximize_is_not_covering(self) -> None:
        window = {
            "floating": True,
            "fullscreen": 1,
            "monitor": 0,
            "at": [0, 57],
            "size": [1920, 1023],
            "class": "google-chrome",
        }
        with mock.patch.object(ventanas, "monitor_by_id", return_value={"x": 0, "y": 0, "width": 1920, "height": 1080, "reserved": [0, 57, 0, 0]}):
            self.assertFalse(ventanas.covers_shell_bar(window))

    def test_full_monitor_float_is_covering(self) -> None:
        window = {
            "floating": True,
            "fullscreen": 0,
            "monitor": 0,
            "at": [0, 0],
            "size": [1920, 1080],
            "class": "xfce4-terminal",
        }
        with mock.patch.object(ventanas, "monitor_by_id", return_value={"x": 0, "y": 0, "width": 1920, "height": 1080, "reserved": [0, 57, 0, 0]}):
            with mock.patch.object(ventanas, "window_bar_height", return_value=28):
                self.assertTrue(ventanas.covers_shell_bar(window))


if __name__ == "__main__":
    unittest.main()
