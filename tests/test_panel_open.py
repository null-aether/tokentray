"""Opening an already visible panel must preserve its contents and position."""

from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from tokentray.app import Controller
from tokentray.ui.panel import DetailPanel


def test_repeated_open_preserves_wayland_panel(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    panel = DetailPanel(lambda: None)
    qtbot.addWidget(panel)
    tray = SimpleNamespace(geometry=Mock(return_value=QRect(400, 500, 1, 1)))
    controller = SimpleNamespace(panel=panel, tray=tray, views=[])
    controller._show_panel_now = lambda: Controller._show_panel_now(controller)

    Controller.show_panel(controller)
    qtbot.waitUntil(panel.isActiveWindow)
    content = panel.content
    position = QPoint(panel.pos())
    anchor = QRect(panel._anchor)
    tray.geometry.reset_mock()
    tray.geometry.return_value = QRect(415, 508, 1, 1)

    # Include several queued requests, as well as one received while visible.
    for _ in range(4):
        Controller.show_panel(controller)
    qapp.processEvents()

    assert panel.isVisible()
    assert panel.content is content
    assert panel.pos() == position
    assert panel._anchor == anchor
    tray.geometry.assert_not_called()

    # Polls still update the contents at the original anchor, even if a click
    # elsewhere within the tray icon has supplied different host coordinates.
    panel.update_views([])
    assert panel._anchor == anchor
    assert panel.pos() == position

    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    other.activateWindow()
    qtbot.waitUntil(lambda: not panel.isVisible())
    Controller.show_panel(controller)
    qtbot.waitUntil(panel.isActiveWindow)
    assert panel._anchor == QRect(415, 508, 1, 1)
    tray.geometry.assert_called_once()


def test_queued_initial_requests_only_open_once(qapp, qtbot):
    panel = DetailPanel(lambda: None)
    qtbot.addWidget(panel)
    tray = SimpleNamespace(geometry=Mock(return_value=QRect(400, 500, 1, 1)))
    controller = SimpleNamespace(panel=panel, tray=tray, views=[])
    controller._show_panel_now = lambda: Controller._show_panel_now(controller)
    for _ in range(4):
        Controller.show_panel(controller)
    qtbot.waitUntil(panel.isVisible)
    qapp.processEvents()
    tray.geometry.assert_called_once()
