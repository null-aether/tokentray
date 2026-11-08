"""Route local alerts and independently deliver enabled webhook notifications.

Windows and native Wayland prefer native banners, retaining custom cards for
recovery actions and submission failures. Wayland cards need layer-shell.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable

from ..core.alerts import AlertEvent
from ..ui.popup import MAX_VISIBLE, ToastManager
from ..ui.wayland import can_position_notifications, is_native_wayland
from .formatting import summarize
from .webhook import Webhook

log = logging.getLogger("tokentray.notify")


class Dispatcher:
    def __init__(
        self,
        toasts: ToastManager,
        webhook: Webhook,
        *,
        native: Callable[[str, str], bool] | None = None,
        native_enabled: bool = True,
    ) -> None:
        self._toasts = toasts
        self._webhook = webhook
        self._native = native
        self._native_enabled = native_enabled

    def set_native_enabled(self, enabled: bool) -> None:
        self._native_enabled = enabled

    def emit(self, events: list[AlertEvent]) -> None:
        if not events:
            return
        for event in events:
            provider = event.provider if event.provider in ("claude", "codex") else "unspecified"
            kind = event.kind if event.kind in ("threshold", "reminder", "info") else "unknown"
            log.info("notification_event provider=%s kind=%s login_required=%s",
                     provider, kind, event.login_required)
        self._emit_local(events)

        if len(events) > MAX_VISIBLE:
            summary = summarize(events)
            self._webhook.send_summary(
                summary.title, summary.body, _worst_priority(events), detail=summary.detail
            )
            return

        for event in events:
            self._webhook.send(event)

    def present(
        self, title: str, body: str, show_custom: Callable[[], None],
        *, force_custom: bool = False,
    ) -> None:
        """Choose a local channel without duplicate or unpositioned flyouts."""
        if sys.platform == "win32" or is_native_wayland():
            if force_custom and self._custom_supported():
                show_custom()
            elif not self.notify_native(title, body):
                self._show_custom(show_custom)
        else:
            show_custom()
            self.notify_native(title, body)

    def _emit_local(self, events: list[AlertEvent]) -> None:
        if sys.platform != "win32" and not is_native_wayland():
            self._toasts.show_alerts(events)
            if len(events) > MAX_VISIBLE:
                summary = summarize(events)
                self.notify_native(summary.title, summary.body)
            else:
                for event in events:
                    self.notify_native(event.title, event.body)
            return

        if any(e.login_required for e in events) and self._custom_supported():
            self._toasts.show_alerts(events)
            return

        if len(events) > MAX_VISIBLE:
            summary = summarize(events)
            self.present(summary.title, summary.body, lambda: self._toasts.show_alerts(events))
        else:
            for event in events:
                self.present(
                    event.title, event.body,
                    lambda event=event: self._toasts.show_alerts([event]),
                )

    def _custom_supported(self) -> bool:
        return not is_native_wayland() or can_position_notifications()

    def _show_custom(self, show_custom: Callable[[], None]) -> None:
        if self._custom_supported():
            show_custom()
        else:
            # An ordinary QWidget would be centered by the compositor. Keep the
            # failure visible in diagnostics rather than putting it over work.
            log.warning("custom_notification_unavailable reason=wayland_positioning_unavailable")

    def notify_native(self, title: str, body: str) -> bool:
        """Return whether submission succeeded, not whether a banner appeared."""
        if self._native_enabled and self._native is not None:
            try:
                return self._native(title, body)
            except Exception:
                log.warning("native notification failed: %s", title, exc_info=True)
        return False


def _worst_priority(events: list[AlertEvent]) -> str:
    order = {"default": 0, "high": 1, "urgent": 2}
    return max((e.priority for e in events), key=lambda p: order.get(p, 0))
