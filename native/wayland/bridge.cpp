// SPDX-License-Identifier: MIT
// A stable C boundary over public Qt/KDE APIs; Python never calls C++ symbols
// or Wayland/Qt private interfaces directly. All calls run on the Qt UI thread.
#include <KStatusNotifierItem>
#include <LayerShellQt/Window>
#include <QIcon>
#include <QMenu>
#include <QWindow>
#include <cstring>
#include <wayland-client.h>

namespace {
void registryGlobal(void *data, wl_registry *, uint32_t, const char *interface, uint32_t version)
{
    if (std::strcmp(interface, "zwlr_layer_shell_v1") == 0 && version >= 4) {
        *static_cast<bool *>(data) = true;
    }
}
void registryRemoved(void *, wl_registry *, uint32_t) {}
}

extern "C" {
bool tokentray_layer_supported()
{
    // Use a separate connection, without dispatching Qt's own event queue.
    auto *display = wl_display_connect(nullptr);
    if (!display) {
        return false;
    }
    bool supported = false;
    const wl_registry_listener listener = {registryGlobal, registryRemoved};
    auto *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, &supported);
    const bool success = wl_display_roundtrip(display) >= 0;
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return success && supported;
}

const char *tokentray_qt_version()
{
    return QT_VERSION_STR;
}

QObject *tokentray_tray_create(QObject *parent)
{
    auto *item = new KStatusNotifierItem(QStringLiteral("tokentray"), parent);
    item->setTitle(QStringLiteral("tokentray"));
    item->setStandardActionsEnabled(false);
    return item;
}

void tokentray_tray_icon(KStatusNotifierItem *item, const QIcon *icon)
{
    item->setIconByPixmap(*icon);
}

void tokentray_tray_menu(KStatusNotifierItem *item, QMenu *menu)
{
    item->setContextMenu(menu);
}

void tokentray_tray_tooltip(KStatusNotifierItem *item, const char *text)
{
    item->setToolTipTitle(QString::fromUtf8(text));
}

void tokentray_tray_visible(KStatusNotifierItem *item, bool visible)
{
    item->setStatus(visible ? KStatusNotifierItem::Active : KStatusNotifierItem::Passive);
}

void tokentray_tray_message(KStatusNotifierItem *item, const char *title, const char *body, int timeout)
{
    item->showMessage(QString::fromUtf8(title), QString::fromUtf8(body), QString(), timeout);
}

const char *tokentray_tray_token(KStatusNotifierItem *item)
{
    static thread_local QByteArray token;
    token = item->providedToken().toUtf8();
    return token.constData();
}

void tokentray_layer_place(QWindow *window, QScreen *screen, int x, int y)
{
    auto *layer = LayerShellQt::Window::get(window);
    layer->setScope(QStringLiteral("tokentray-details"));
    layer->setScreen(screen);
    layer->setAnchors(LayerShellQt::Window::Anchors{LayerShellQt::Window::AnchorTop}
                      | LayerShellQt::Window::AnchorLeft);
    layer->setMargins(QMargins(x, y, 0, 0));
    // Offsets are relative to the full output; Python already avoids panel struts.
    layer->setExclusiveZone(-1);
    layer->setLayer(LayerShellQt::Window::LayerTop);
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
}
}
