"""Optional native integration, without requiring a compositor or KDE in CI."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QGuiApplication

from tokentray.ui import wayland


@pytest.fixture(autouse=True)
def reset_bridge_cache():
    cached = wayland.native_bridge
    cached.cache_clear()
    yield
    cached.cache_clear()


@pytest.mark.parametrize("supported", [True, False])
def test_backend_checks_compositor_protocol(qapp, monkeypatch, supported):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    bridge = SimpleNamespace(API_VERSION=2, layer_supported=lambda: supported)
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(Bridge=lambda: bridge))
    assert wayland.native_bridge() is (bridge if supported else None)


def test_backend_rejects_incompatible_qt(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    factory = Mock(side_effect=RuntimeError("Qt version mismatch"))
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(Bridge=factory))
    assert wayland.native_bridge() is None


def test_xcb_does_not_load_native_integration(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "xcb")
    factory = Mock(side_effect=AssertionError("native bridge must not be loaded"))
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(Bridge=factory))
    assert wayland.native_bridge() is None
    factory.assert_not_called()


def test_native_activation_preserves_tray_position_and_token(qapp, monkeypatch):
    class Item(QObject):
        activateRequested = Signal(bool, QPoint)

    item = Item()
    bridge = SimpleNamespace(create_tray=lambda _: item, tray_token=lambda _: b"test-activation")
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(pointer=id))
    monkeypatch.delenv("XDG_ACTIVATION_TOKEN", raising=False)
    icon = wayland.NativeTrayIcon(bridge)
    opened = []
    icon.activated.connect(opened.append)
    item.activateRequested.emit(True, QPoint(-250, 1050))
    assert icon.geometry().center() == QPoint(-250, 1050)
    assert opened
    item.activateRequested.emit(True, QPoint(-243, 1057))
    assert icon.geometry().center() == QPoint(-250, 1050)
    item.activateRequested.emit(True, QPoint(-150, 1050))
    assert icon.geometry().center() == QPoint(-150, 1050)
    import os

    assert os.environ["XDG_ACTIVATION_TOKEN"] == "test-activation"
    # Activating from a keyboard/menu without coordinates keeps the last tray anchor.
    item.activateRequested.emit(True, QPoint())
    assert icon.geometry().center() == QPoint(-150, 1050)
    monkeypatch.setattr(QGuiApplication, "screenAt", lambda p: "left" if p.x() < 0 else "right")
    item.activateRequested.emit(True, QPoint(-5, 500))
    item.activateRequested.emit(True, QPoint(5, 500))
    assert icon.geometry().center() == QPoint(5, 500)
    icon.close()
    icon.close()


def test_layer_placement_uses_output_local_logical_coordinates(monkeypatch):
    bridge = SimpleNamespace(layer_anchor=Mock())
    monkeypatch.setattr(wayland, "native_bridge", lambda: bridge)
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(pointer=lambda value: value))
    handle = Mock()
    panel = SimpleNamespace(winId=Mock(), windowHandle=lambda: handle,
                            size=lambda: QSize(420, 300), rect=lambda: QRect(0, 0, 420, 300))
    screen = SimpleNamespace(geometry=lambda: QRect(-1920, -200, 1920, 1080))
    assert wayland.place_panel(panel, screen, QPoint(-250, 870))
    panel.winId.assert_called_once()
    bridge.layer_anchor.assert_called_once_with(handle, screen, 6, 1460, 0, 0, -36)
    assert handle.setMask.call_args.args[0].boundingRect() == QRect(40, 40, 340, 220)


def test_old_native_package_falls_back_safely(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(Bridge=lambda: object()))
    assert wayland.native_bridge() is None


@pytest.mark.parametrize("point,anchors,margins", [
    (QPoint(600, 10), 5, (390, -36, 0, 0)),
    (QPoint(600, 1070), 6, (390, 0, 0, -36)),
    (QPoint(10, 600), 5, (-36, 450, 0, 0)),
    (QPoint(1910, 600), 9, (0, 450, -36, 0)),
])
def test_visible_card_follows_panel_edge(point, anchors, margins):
    assert wayland.layer_placement(QRect(0, 0, 1920, 1080), point, QSize(420, 300), 40) == (
        anchors, *margins)


@pytest.mark.parametrize("point", [QPoint(1800, 1060), QPoint(1800, 1075)])
def test_bottom_edge_gap_does_not_depend_on_click_height(point):
    assert wayland.layer_placement(QRect(0, 0, 1920, 1080), point, QSize(420, 300), 40) == (
        6, 1536, 0, 0, -36)
