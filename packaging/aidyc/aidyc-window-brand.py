#!/usr/bin/env python3
"""Brand AidyC's XWayland window: WM_CLASS=aidyc and _NET_WM_ICON from logo."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import struct
import sys
import time
from pathlib import Path

ICON_CANDIDATES = (
    Path("/usr/share/pixmaps/aidyc.png"),
    Path("/usr/share/icons/hicolor/256x256/apps/aidyc.png"),
    Path("/usr/share/icons/hicolor/128x128/apps/aidyc.png"),
    Path("/opt/aidyc/AidyC/Aidylogo.png"),
)
WM_CLASS = b"aidyc"
WM_CLASS_NAME = b"AidyC"


class X11:
    def __init__(self) -> None:
        lib = ctypes.util.find_library("X11")
        if not lib:
            raise RuntimeError("libX11 not found")
        self.x11 = ctypes.CDLL(lib)
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x11.XInternAtom.restype = ctypes.c_ulong
        self.x11.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.x11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.x11.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        self.x11.XFree.argtypes = [ctypes.c_void_p]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("cannot open X display")
        self.root = self.x11.XDefaultRootWindow(self.display)
        self.XA_ATOM = 4
        self.XA_STRING = 31
        self.XA_CARDINAL = 6
        self.PropModeReplace = 0
        self.pid_atom = self.x11.XInternAtom(self.display, b"_NET_WM_PID", 0)
        self.icon_atom = self.x11.XInternAtom(self.display, b"_NET_WM_ICON", 0)
        self.wm_class_atom = self.x11.XInternAtom(self.display, b"WM_CLASS", 0)

    def close(self) -> None:
        self.x11.XCloseDisplay(self.display)

    def windows_for_pid(self, pid: int) -> list[int]:
        found: list[int] = []

        def walk(window: int) -> None:
            if self._window_pid(window) == pid:
                found.append(window)
            root_return = ctypes.c_ulong()
            parent_return = ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            nchildren = ctypes.c_uint()
            status = self.x11.XQueryTree(
                self.display,
                window,
                ctypes.byref(root_return),
                ctypes.byref(parent_return),
                ctypes.byref(children),
                ctypes.byref(nchildren),
            )
            if status == 0 or not children:
                return
            try:
                for index in range(nchildren.value):
                    walk(children[index])
            finally:
                self.x11.XFree(children)

        walk(self.root)
        return found

    def _window_pid(self, window: int) -> int | None:
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ubyte)()
        status = self.x11.XGetWindowProperty(
            self.display,
            window,
            self.pid_atom,
            0,
            1,
            0,
            self.XA_CARDINAL,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(prop),
        )
        if status != 0 or not prop or nitems.value < 1 or actual_format.value != 32:
            if prop:
                self.x11.XFree(prop)
            return None
        try:
            return int(ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))[0])
        finally:
            self.x11.XFree(prop)

    def set_wm_class(self, window: int) -> None:
        payload = WM_CLASS + b"\0" + WM_CLASS_NAME + b"\0"
        buf = ctypes.create_string_buffer(payload)
        self.x11.XChangeProperty(
            self.display,
            window,
            self.wm_class_atom,
            self.XA_STRING,
            8,
            self.PropModeReplace,
            buf,
            len(payload),
        )

    def set_icon(self, window: int, rgba: bytes, width: int, height: int) -> None:
        # _NET_WM_ICON: width, height, then width*height CARDINALs (ARGB)
        count = 2 + width * height
        values = (ctypes.c_ulong * count)()
        values[0] = width
        values[1] = height
        for index in range(width * height):
            r, g, b, a = rgba[index * 4 : index * 4 + 4]
            values[2 + index] = (a << 24) | (r << 16) | (g << 8) | b
        self.x11.XChangeProperty(
            self.display,
            window,
            self.icon_atom,
            self.XA_CARDINAL,
            32,
            self.PropModeReplace,
            ctypes.cast(values, ctypes.c_void_p),
            count,
        )

    def flush(self) -> None:
        self.x11.XFlush(self.display)


def _load_icon() -> tuple[bytes, int, int] | None:
    path = next((candidate for candidate in ICON_CANDIDATES if candidate.is_file()), None)
    if path is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        Image = None  # type: ignore[assignment]
    if Image is not None:
        image = Image.open(path).convert("RGBA")
        size = 64 if max(image.size) > 64 else max(image.size)
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        return image.tobytes(), size, size
    # Minimal PNG reader fallback is omitted; Pillow is present on AidyCOS.
    return None


def brand(pid: int, *, timeout: float = 20.0) -> int:
    deadline = time.time() + timeout
    x11 = None
    icon = _load_icon()
    try:
        while time.time() < deadline:
            if x11 is None:
                try:
                    x11 = X11()
                except RuntimeError:
                    time.sleep(0.25)
                    continue
            windows = x11.windows_for_pid(pid)
            if windows:
                for window in windows:
                    x11.set_wm_class(window)
                    if icon is not None:
                        rgba, width, height = icon
                        x11.set_icon(window, rgba, width, height)
                x11.flush()
                return 0
            time.sleep(0.25)
            if not Path(f"/proc/{pid}").exists():
                return 1
        return 1
    finally:
        if x11 is not None:
            x11.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        return brand(args.pid, timeout=args.timeout)
    except Exception as error:  # noqa: BLE001 — best-effort branding helper
        print(f"aidyc-window-brand: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
