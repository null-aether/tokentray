"""Optional native integration, without requiring a compositor or KDE in CI."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, Signal
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
    bridge = SimpleNamespace(layer_supported=lambda: supported)
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
    import os

    assert os.environ["XDG_ACTIVATION_TOKEN"] == "test-activation"
    # Activating from a keyboard/menu without coordinates keeps the last tray anchor.
    item.activateRequested.emit(True, QPoint())
    assert icon.geometry().center() == QPoint(-250, 1050)
    icon.close()
    icon.close()


def test_layer_offsets_use_output_local_logical_coordinates(monkeypatch):
    bridge = SimpleNamespace(layer_place=Mock())
    monkeypatch.setattr(wayland, "native_bridge", lambda: bridge)
    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(pointer=lambda value: value))
    handle = object()
    panel = SimpleNamespace(winId=Mock(), windowHandle=lambda: handle)
    screen = SimpleNamespace(geometry=lambda: QRect(-1920, -200, 1920, 1080))
    assert wayland.place_panel(panel, screen, QPoint(-250, 30))
    panel.winId.assert_called_once()
    bridge.layer_place.assert_called_once_with(handle, screen, 1670, 230)
