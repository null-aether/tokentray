"""Wayland alerts use one channel and positioned cards never activate the app."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QWidget

from tokentray.core.alerts import AlertEvent
from tokentray.notify import dispatcher as routing
from tokentray.ui import popup, wayland


@pytest.fixture
def channels(qapp, monkeypatch):
    monkeypatch.setattr(routing, "is_native_wayland", lambda: True)
    monkeypatch.setattr(routing, "can_position_notifications", lambda: True)
    cards, webhook, native = Mock(), Mock(), Mock(return_value=True)
    return routing.Dispatcher(cards, webhook, native=native), cards, webhook, native


def alert():
    return AlertEvent("threshold", "claude.5h", "Claude Code", "48% remaining", provider="claude")


def test_threshold_is_native_only_and_reason_is_logged(channels, caplog):
    dispatcher, cards, webhook, native = channels
    with caplog.at_level(logging.INFO, logger="tokentray.notify"):
        dispatcher.emit([alert()])
    native.assert_called_once()
    cards.show_alerts.assert_not_called()
    webhook.send.assert_called_once()
    assert "provider=claude kind=threshold login_required=False" in caplog.text


@pytest.mark.parametrize("disabled", [True, False])
def test_disabled_or_failed_native_channel_has_one_positioned_fallback(channels, disabled):
    dispatcher, cards, webhook, native = channels
    dispatcher.set_native_enabled(not disabled)
    native.return_value = False
    dispatcher.emit([alert()])
    cards.show_alerts.assert_called_once()
    assert native.call_count == int(not disabled)
    webhook.send.assert_called_once()


def test_login_actions_use_only_the_custom_card(channels):
    dispatcher, cards, _, native = channels
    event = alert()
    event.login_required = True
    dispatcher.emit([event])
    cards.show_alerts.assert_called_once_with([event])
    native.assert_not_called()


def test_unsupported_layer_backend_never_falls_back_to_a_centered_card(channels, monkeypatch, caplog):
    dispatcher, cards, webhook, native = channels
    monkeypatch.setattr(routing, "can_position_notifications", lambda: False)
    native.return_value = False
    dispatcher.emit([alert()])
    cards.show_alerts.assert_not_called()
    webhook.send.assert_called_once()
    assert "wayland_positioning_unavailable" in caplog.text


def test_login_without_positioning_still_has_a_native_notification(channels, monkeypatch):
    dispatcher, cards, _, native = channels
    monkeypatch.setattr(routing, "can_position_notifications", lambda: False)
    event = alert()
    event.login_required = True
    dispatcher.emit([event])
    native.assert_called_once()
    cards.show_alerts.assert_not_called()


def test_tray_unavailable_warning_uses_the_same_positioning_guard(channels, monkeypatch):
    from tokentray.app import Controller

    dispatcher, cards, _, native = channels
    monkeypatch.setattr(routing, "can_position_notifications", lambda: False)
    Controller._on_tray_unavailable(SimpleNamespace(dispatcher=dispatcher, toasts=cards))
    native.assert_called_once()
    cards.show.assert_not_called()


def test_native_summary_does_not_create_a_custom_stack(channels):
    dispatcher, cards, webhook, native = channels
    dispatcher.emit([alert() for _ in range(popup.MAX_VISIBLE + 1)])
    native.assert_called_once()
    cards.show_alerts.assert_not_called()
    webhook.send_summary.assert_called_once()


def test_positioned_card_skips_unsupported_animation_and_does_not_open_details(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(wayland, "place_notification", lambda *_a, **_kw: True)
    manager = popup.ToastManager()
    manager.on_activated = Mock()
    card = popup.Toast(title="Claude Code", body="48% remaining")
    card.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    qtbot.addWidget(card)
    move, opacity = Mock(), Mock()
    monkeypatch.setattr(card, "move", move)
    monkeypatch.setattr(card, "setWindowOpacity", opacity)
    manager.show(card)
    assert card.isVisible() and card._wayland_positioned
    assert card._dismiss.isActive()
    move.assert_not_called()
    opacity.assert_not_called()
    manager.on_activated.assert_not_called()
    closed = []
    card.closed.connect(closed.append)
    card.dismiss()
    card.dismiss()
    assert closed == [card]
    assert not manager._toasts


def test_wayland_hover_uses_local_events_not_a_stale_global_cursor(qapp, qtbot, monkeypatch):
    card = popup.Toast(title="t", body="b")
    qtbot.addWidget(card)
    card._wayland_positioned = True
    monkeypatch.setattr(popup.QCursor, "pos", lambda: card.mapToGlobal(card._card.geometry().center()))
    for widget in [card, *card.findChildren(QWidget)]:
        monkeypatch.setattr(widget, "underMouse", lambda: False)
    assert not card.hovered()
    monkeypatch.setattr(card._card, "underMouse", lambda: True)
    assert card.hovered()


@pytest.mark.parametrize("from_top,anchors,margins", [
    (True, 9, (0, 76, -24, 0)), (False, 10, (0, 0, -24, 76)),
])
def test_corner_placement_uses_nonactivating_native_function(monkeypatch, from_top, anchors, margins):
    bridge = SimpleNamespace(API_VERSION=3, layer_notification=Mock())
    monkeypatch.setattr(wayland, "native_bridge", lambda: bridge)
    monkeypatch.setattr(wayland.QGuiApplication, "screenAt", lambda _p: "screen")
    import sys

    monkeypatch.setitem(sys.modules, "tokentray_wayland", SimpleNamespace(pointer=lambda obj: obj))
    handle = Mock()
    card = SimpleNamespace(winId=Mock(), windowHandle=lambda: handle, rect=lambda: QRect(0, 0, 452, 220),
                           update=Mock())
    assert wayland.place_notification(card, QRect(-1920, 0, 1920, 1080), from_top=from_top, offset=100)
    bridge.layer_notification.assert_called_once_with(handle, "screen", anchors, *margins)
    assert handle.setMask.call_args.args[0].boundingRect() == QRect(40, 40, 372, 140)
    card.update.assert_called_once()


@pytest.mark.parametrize("api,supported", [(None, False), (2, False), (3, True)])
def test_notifications_require_the_nonactivating_bridge(monkeypatch, api, supported):
    bridge = SimpleNamespace(API_VERSION=api) if api is not None else None
    monkeypatch.setattr(wayland, "native_bridge", lambda: bridge)
    assert wayland.can_position_notifications() is supported


def test_restacking_updates_layer_margins_without_a_move_animation(qapp, qtbot, monkeypatch):
    placement = Mock(return_value=True)
    monkeypatch.setattr(wayland, "place_notification", placement)
    manager = popup.ToastManager()
    lower = popup.Toast(title="lower", body="b")
    upper = popup.Toast(title="upper", body="b")
    for card in (lower, upper):
        card.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    qtbot.addWidget(lower)
    qtbot.addWidget(upper)
    manager.show(lower)
    manager.show(upper)
    assert placement.call_args.kwargs["offset"] > 0
    lower.dismiss()
    assert manager._toasts == [upper]
    assert placement.call_args.kwargs["offset"] == 0
    manager.clear(immediate=True)
