# Native positioned Wayland panels

This optional Linux package uses **LayerShellQt** to place the detail panel and
**KStatusNotifierItem** to retain the coordinates supplied by the tray host's
StatusNotifierItem `Activate(x, y)` request. Qt's built-in tray adaptor drops
those coordinates before emitting `activated()`.

The small compiled bridge calls only public library APIs through a typed C
boundary. It does not load KWin scripts, install window rules, inspect Qt private
objects, or guess the tray position from the cursor. Layer-shell is selected per
panel window; other app windows retain their normal Wayland roles.

The compositor must expose `zwlr_layer_shell_v1` version 4 or later. The bridge
checks this on its own Wayland connection before enabling the native backend.
It also checks that the system Qt used to build it has the same major/minor
version as PySide6. If either check fails, the normal app remains usable with
compositor-controlled positioning.

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

After clicking the tray icon, subsequent opens and data refreshes reuse that
anchor. Before the first tray activation, no host coordinates are available and
the app uses its usual fallback anchor. Output offsets and window sizes are in
logical pixels; negative output origins and fractional scaling need no pixel
ratio conversion. Rebuild this optional package after upgrading system Qt to a
different minor version.

## Desktop checks

`tests/manual_panel_lifecycle.py` checks first-open, focus dismissal, reopening
and Escape. Also check real tray activation on every supported compositor,
top/bottom and vertical panels, output edges, multiple outputs, fractional
scaling, content resizing, language/menu rebuilds, and clean process shutdown.
Offscreen tests cannot verify compositor placement.
