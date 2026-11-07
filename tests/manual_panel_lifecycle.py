"""Check real compositor exposure and focus, without credentials or networking.

Run on a desktop, separately for each backend (the pytest suite is offscreen):
    QT_QPA_PLATFORM=wayland uv run python tests/manual_panel_lifecycle.py
    QT_QPA_PLATFORM=xcb uv run python tests/manual_panel_lifecycle.py

Two short-lived windows appear. The panel must open before any other window
has supplied a parent/input serial, dismiss on deactivation, reopen and accept
Escape from a child button. A nonzero exit means a lifecycle check failed.
"""

import json
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from tokentray.ui.panel import DetailPanel


def main() -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    panel = DetailPanel(lambda: None)
    other = QWidget()
    other.setWindowTitle("TokenTray focus check")
    other.resize(220, 100)
    failures = []

    def check(stage, expected):
        handle = panel.windowHandle()
        actual = (panel.isVisible(), bool(handle and handle.isExposed()), panel.isActiveWindow())
        print(json.dumps({"stage": stage, "platform": app.platformName(),
                          "visible": actual[0], "exposed": actual[1], "active": actual[2],
                          "passed": actual == expected}), flush=True)
        if actual != expected:
            failures.append(stage)

    def focus_other():
        other.show()
        other.raise_()
        other.activateWindow()

    def escape():
        button = panel.findChild(QPushButton, "panel-refresh")
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Escape)

    QTimer.singleShot(100, lambda: panel.popup_at(None))
    QTimer.singleShot(1000, lambda: check("opened", (True, True, True)))
    QTimer.singleShot(1400, focus_other)
    QTimer.singleShot(2300, lambda: check("other-focused", (False, False, False)))
    QTimer.singleShot(2700, lambda: panel.popup_at(None))
    QTimer.singleShot(3300, lambda: check("reopened", (True, True, True)))
    QTimer.singleShot(3500, escape)
    QTimer.singleShot(3900, lambda: check("escape", (False, False, False)))
    QTimer.singleShot(4100, app.quit)
    app.exec()
    panel.close()
    other.close()
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
