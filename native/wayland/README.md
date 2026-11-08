# Native positioned Wayland panels and notifications

This optional Linux package uses **LayerShellQt** to place the detail panel and
custom notification cards. It uses **KStatusNotifierItem** to retain the
coordinates supplied by the tray host's
StatusNotifierItem `Activate(x, y)` request. Qt's built-in tray adaptor drops
those coordinates before emitting `activated()`.

The small compiled bridge calls only public library APIs through a typed C
boundary. It does not load KWin scripts, install window rules, inspect Qt private
objects, or guess the tray position from the cursor. Layer-shell is selected per
detail/notification window; other app windows retain their normal Wayland roles.

The compositor must expose `zwlr_layer_shell_v1` version 4 or later. The bridge
checks this on its own Wayland connection before enabling the native backend.
It also checks that the system Qt used to build it has the same major/minor
version as PySide6. If either check fails, the normal app remains usable with
compositor-controlled detail-panel positioning and system notifications.

## Build and install

Install a C++ compiler, pkg-config and development files for Qt 6.11+, Wayland,
LayerShellQt 6.6+ and KF6StatusNotifierItem. CMake/Ninja are supplied by the Python
build backend when missing. On Arch the relevant packages are `base-devel`,
`qt6-base`, `qt6-wayland`, `wayland`, `layer-shell-qt` and `kstatusnotifieritem`.
PySide6 and system Qt must use matching major/minor versions.

From the repository root:

```bash
uv tool install --force --python 3.12 --with ./native/wayland .
tokentray config set linux.force_xwayland false
tokentray stop
tokentray
```

SNI provides a click point, not the icon rectangle. Nearby clicks reuse the same
anchor, with a tolerance derived from Qt's standard toolbar icon-button size;
a larger move or a different output updates it. Data refreshes retain the anchor.
Layer-shell anchors the visible card 4 logical pixels outside the desktop
panel's reserved area, compensating for the transparent shadow padding. The
padding is excluded from the native input region so it cannot block tray icons.
Before the first tray activation, no host coordinates are available and the app
uses its usual fallback anchor. Layer-shell offsets and Qt window sizes are in
logical pixels; verify the tray host's coordinate convention on mixed-DPI setups.
Rebuild this optional package after upgrading system Qt to a
different minor version. The Python wrapper and its compiled library must use
the same bridge API version. TokenTray requires API 2 (package 0.2.0+) for detail
panels and API 3 (package 0.3.0+) for custom notifications.

Ordinary alerts on native Wayland use one desktop notification when enabled.
Action cards, or fallbacks when native delivery fails or is disabled, use
layer-shell surfaces with no keyboard interactivity or activation on show.
Their visible edge sits 16 logical pixels inside the desktop work area;
`popup.position` selects the top or bottom right corner. Stacking updates the
layer margins and schedules a QWidget repaint to commit the protocol state.
Transparent shadow padding is excluded from input. Without API 3, TokenTray
does not show custom cards on native Wayland; system notifications still work.

## Desktop checks

`tests/manual_panel_lifecycle.py` checks first-open, focus dismissal, reopening
and Escape. Also check real tray activation on every supported compositor,
top/bottom and vertical panels, output edges, multiple outputs, fractional
scaling, content resizing, language/menu rebuilds, and clean process shutdown.
Offscreen tests cannot verify compositor placement.
Check notification corners, expiry, hover, close/action buttons and stack
compaction while another app retains focus. A successful ordinary native alert
must not also create a custom card or open the detail panel.
