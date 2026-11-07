"""Panel dismissal must not depend on a parentless Wayland popup grab."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QPushButton, QWidget

from tokentray.ui.panel import DetailPanel


@pytest.mark.parametrize("platform", ["wayland", "wayland-egl", "xcb", "windows", "cocoa"])
def test_window_type_matches_platform(qapp, qtbot, monkeypatch, platform):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: platform)
    panel = DetailPanel(lambda: None)
    qtbot.addWidget(panel)
    expected = Qt.WindowType.Tool if platform.startswith("wayland") else Qt.WindowType.Popup
    assert panel.windowType() == expected


@pytest.fixture
def wayland_panel(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    panel = DetailPanel(lambda: None)
    qtbot.addWidget(panel)
    panel.popup_at(None)
    qtbot.waitUntil(panel.isActiveWindow)
    return panel


def test_wayland_dismisses_on_window_deactivation_and_reopens(qapp, qtbot, wayland_panel):
    panel = wayland_panel
    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    other.activateWindow()
    qtbot.waitUntil(lambda: not panel.isVisible())
    # A completed background poll must not resurrect a dismissed panel.
    panel.update_views([])
    assert not panel.isVisible()
    panel.popup_at(None)
    qtbot.waitUntil(panel.isActiveWindow)
    assert panel.isVisible()


def test_wayland_child_focus_and_refresh_keep_panel_open(qapp, qtbot, wayland_panel):
    panel = wayland_panel
    button = panel.findChild(QPushButton, "panel-refresh")
    button.setFocus()
    qapp.processEvents()
    assert panel.isVisible()
    panel.update_views([])
    qapp.processEvents()
    assert panel.isVisible()


def test_wayland_escape_from_child_hides_panel(qapp, qtbot, wayland_panel):
    button = wayland_panel.findChild(QPushButton, "panel-refresh")
    button.setFocus()
    qtbot.keyClick(button, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not wayland_panel.isVisible())
