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
from PySide6.QtGui import QGuiApplication, QIcon, QRegion
from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon

log = logging.getLogger("tokentray.wayland")


def is_native_wayland() -> bool:
    app = QGuiApplication.instance()
    return isinstance(app, QGuiApplication) and app.platformName().startswith("wayland")


def can_position_notifications() -> bool:
    bridge = native_bridge()
    return bridge is not None and getattr(bridge, "API_VERSION", 0) >= 3


@lru_cache(maxsize=1)
def native_bridge():
    if not QGuiApplication.platformName().startswith("wayland"):
        return None
    try:
        from tokentray_wayland import Bridge

        bridge = Bridge()
        if getattr(bridge, "API_VERSION", 1) < 2:
            log.warning("native positioning requires tokentray-wayland >= 0.2.0")
            return None
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
            # SNI supplies a mouse point, not the icon's rectangle. Keep nearby
            # clicks on the same icon from moving the flyout; use the style's
            # standard icon-button extent rather than rounding screen coordinates.
            style = QApplication.style()
            extent = (style.pixelMetric(QStyle.PixelMetric.PM_ToolBarIconSize)
                      + 2 * style.pixelMetric(QStyle.PixelMetric.PM_ToolBarItemMargin))
            previous = self._anchor.center()
            same_output = (QGuiApplication.screenAt(previous) == QGuiApplication.screenAt(position))
            nearby = max(abs(position.x() - previous.x()), abs(position.y() - previous.y())) <= extent
            if self._anchor.isNull() or not same_output or not nearby:
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


def layer_placement(area: QRect, anchor: QPoint, size: QSize, padding: int, gap: int = 4):
    """Anchor the visible card to a panel edge, keeping shadow padding transparent.

    Layer-shell's nonexclusive surfaces respect the desktop panel's reserved
    space. The compositor supplies the perpendicular position, so clicking near
    the top or bottom of the same tray icon cannot change the visible gap.
    """
    point = anchor - area.topLeft()
    distances = {
        "top": point.y(), "bottom": area.height() - point.y(),
        "left": point.x(), "right": area.width() - point.x(),
    }
    edge = min(distances, key=distances.get)
    inset = gap - padding
    if edge in ("top", "bottom"):
        x = max(inset, min(point.x() - size.width() // 2, area.width() - size.width() - inset))
        # LayerShellQt anchors: top=1, bottom=2, left=4, right=8.
        return (5, x, inset, 0, 0) if edge == "top" else (6, x, 0, 0, inset)
    y = max(inset, min(point.y() - size.height() // 2, area.height() - size.height() - inset))
    return (5, inset, y, 0, 0) if edge == "left" else (9, 0, y, inset, 0)


def place_panel(panel, screen, anchor: QPoint) -> bool:
    bridge = native_bridge()
    if bridge is None or screen is None:
        return False
    from tokentray_wayland import pointer

    from .popup import SHADOW_MARGIN

    # Create the QWidget's QWindow before first show, while it still has no
    # visible surface role. LayerShellQt installs the per-window integration.
    panel.winId()

    # The shadow may extend over the desktop panel, but it must not intercept
    # clicks on tray icons below it. QWindow's mask defines the native input area.
    panel.windowHandle().setMask(QRegion(panel.rect().adjusted(
        SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN, -SHADOW_MARGIN)))
    placement = layer_placement(screen.geometry(), anchor, panel.size(), SHADOW_MARGIN)
    bridge.layer_anchor(pointer(panel.windowHandle()), pointer(screen), *placement)
    return True


def place_notification(toast, area: QRect, *, from_top: bool, offset: int) -> bool:
    bridge = native_bridge()
    if bridge is None or getattr(bridge, "API_VERSION", 0) < 3:
        return False
    screen = QGuiApplication.screenAt(area.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return False
    from tokentray_wayland import pointer

    from .popup import EDGE_MARGIN, SHADOW_MARGIN

    toast.winId()
    handle = toast.windowHandle()
    handle.setMask(QRegion(toast.rect().adjusted(
        SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN, -SHADOW_MARGIN)))
    inset = EDGE_MARGIN - SHADOW_MARGIN
    placement = ((9, 0, inset + offset, inset, 0) if from_top
                 else (10, 0, 0, inset, inset + offset))
    bridge.layer_notification(pointer(handle), pointer(screen), *placement)
    # Margin changes are double-buffered Wayland state. A visible, otherwise
    # static widget needs a paint/commit for a restacked card to move.
    toast.update()
    return True
