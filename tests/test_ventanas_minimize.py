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


if __name__ == "__main__":
    unittest.main()
