"""Optional, compiled public-API bridge. Never loaded on non-Wayland backends."""

import ctypes
from pathlib import Path

from PySide6.QtCore import qVersion
from shiboken6 import getCppPointer, wrapInstance


def pointer(value):
    return getCppPointer(value)[0]


class Bridge:
    API_VERSION = 2

    def __init__(self):
        self.library = ctypes.CDLL(str(Path(__file__).with_name("libtokentray_wayland.so")))
        try:
            api = self.library.tokentray_bridge_api
        except AttributeError as exc:
            raise RuntimeError("Wayland bridge binary is older than its Python wrapper") from exc
        api.restype = ctypes.c_int
        api.argtypes = []
        if api() != self.API_VERSION:
            raise RuntimeError("Wayland bridge binary and Python wrapper have different API versions")
        signatures = {
            "layer_supported": (ctypes.c_bool, []),
            "qt_version": (ctypes.c_char_p, []),
            "tray_create": (ctypes.c_void_p, [ctypes.c_void_p]),
            "tray_icon": (None, [ctypes.c_void_p, ctypes.c_void_p]),
            "tray_menu": (None, [ctypes.c_void_p, ctypes.c_void_p]),
            "tray_tooltip": (None, [ctypes.c_void_p, ctypes.c_char_p]),
            "tray_visible": (None, [ctypes.c_void_p, ctypes.c_bool]),
            "tray_message": (None, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]),
            "tray_token": (ctypes.c_char_p, [ctypes.c_void_p]),
            "layer_anchor": (None, [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 5),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.library, "tokentray_" + name)
            function.restype = result
            function.argtypes = arguments
            setattr(self, name, function)
        built = self.qt_version().decode()
        if built.split(".")[:2] != qVersion().split(".")[:2]:
            raise RuntimeError(f"Wayland bridge uses Qt {built}; PySide6 uses Qt {qVersion()}")

    def create_tray(self, parent):
        from PySide6.QtCore import QObject

        return wrapInstance(self.tray_create(pointer(parent)), QObject)
