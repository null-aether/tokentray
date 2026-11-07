"""Optional layer-shell positioning and a tray host that preserves click coordinates.

The native package links public LayerShellQt and KStatusNotifierItem APIs.
The regular Qt backend remains available when the package, matching Qt runtime,
or compositor protocol is missing. There are no compositor scripts or rules.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QSystemTrayIcon

log = logging.getLogger("tokentray.wayland")


@lru_cache(maxsize=1)
def native_bridge():
    if not QGuiApplication.platformName().startswith("wayland"):
        return None
    try:
        from tokentray_wayland import Bridge

        bridge = Bridge()
        if not bridge.layer_supported():
            log.info("layer-shell v4 unavailable; keeping the standard Wayland window")
            return None
        return bridge
    except ImportError:
        return None
    except (OSError, RuntimeError) as exc:
        log.warning("native Wayland integration unavailable: %s", exc)
        return None


class NativeTrayIcon(QObject):
    """The small QSystemTrayIcon surface used by Tray, with native SNI coordinates."""

    activated = Signal(object)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        from tokentray_wayland import pointer

        self._bridge = bridge
        self._pointer = pointer
        self._item = bridge.create_tray(self)
        self._item.activateRequested.connect(self._activate)
        self._anchor = QRect()
        self._menu = None
        self._tooltip = ""
        self._icon = QIcon()
        QGuiApplication.instance().aboutToQuit.connect(self.close)

    def _activate(self, _active: bool, position: QPoint) -> None:
        if not position.isNull():
            self._anchor = QRect(position, QSize(1, 1))
        token = self._bridge.tray_token(self._pointer(self._item))
        if token:
            os.environ["XDG_ACTIVATION_TOKEN"] = token.decode()
        self.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    def geometry(self):
        return QRect(self._anchor)

    def setIcon(self, icon):  # noqa: N802 - matches QSystemTrayIcon
        self._icon = QIcon(icon)
        self._bridge.tray_icon(self._pointer(self._item), self._pointer(icon))

    def icon(self):
        return QIcon(self._icon)

    def setToolTip(self, text):  # noqa: N802
        self._tooltip = text
        self._bridge.tray_tooltip(self._pointer(self._item), text.encode())

    def toolTip(self):  # noqa: N802
        return self._tooltip

    def setContextMenu(self, menu):  # noqa: N802
        # KStatusNotifierItem owns its QMenu; retain the old wrapper until the
        # native setter has finished replacing it, then keep the new one alive.
        previous = self._menu
        self._bridge.tray_menu(self._pointer(self._item), self._pointer(menu))
        self._menu = menu
        del previous

    def show(self):
        self._bridge.tray_visible(self._pointer(self._item), True)

    def hide(self):
        self._bridge.tray_visible(self._pointer(self._item), False)

    def close(self):
        # Dispose while QApplication and its D-Bus/event machinery still exist.
        # KStatusNotifierItem owns the exported menu and invalidates its wrapper.
        from shiboken6 import delete

        if self._item is not None:
            delete(self._item)
            self._item = None
            self._menu = None

    def showMessage(self, title, body, _icon, timeout):  # noqa: N802
        self._bridge.tray_message(self._pointer(self._item), title.encode(), body.encode(), timeout)


def place_panel(panel, screen, position: QPoint) -> bool:
    bridge = native_bridge()
    if bridge is None or screen is None:
        return False
    from tokentray_wayland import pointer

    # Create the QWidget's QWindow before first show, while it still has no
    # visible surface role. LayerShellQt installs the per-window integration.
    panel.winId()
    origin = screen.geometry().topLeft()
    local = position - origin
    bridge.layer_place(pointer(panel.windowHandle()), pointer(screen), local.x(), local.y())
    return True
