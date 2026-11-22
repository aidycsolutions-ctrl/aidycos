// AidyCOS fork of ar-Raqmi/hyprland-csd-minimize (MIT).
// Adapted for Hyprland 0.55.2 plugin ABI used by packaging/hyprland/hyprbars-src,
// and passes the window address to ventanas so async exec cannot hit the wrong client.
#define WLR_USE_UNSTABLE

#include <cstdlib>
#include <format>
#include <string>
#include <thread>
#include <unordered_map>

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/config/values/types/StringValue.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/xwayland/XSurface.hpp>

class CCSDMinimizePlugin {
  public:
    void init(HANDLE handle) {
        m_handle = handle;

        m_minimizeCommandVal = addCommand(
            "plugin:csd-minimize:command",
            "Command when a CSD minimize button is pressed (window address is appended)",
            "true");
        m_maximizeCommandVal = addCommand(
            "plugin:csd-minimize:maximize_command",
            "Command when a CSD set_maximized is pressed (native maximize suppressed when set)",
            "");
        m_unmaximizeCommandVal = addCommand(
            "plugin:csd-minimize:unmaximize_command",
            "Command when a CSD unset_maximized is pressed (native unmaximize suppressed when set)",
            "");
        m_fullscreenCommandVal = addCommand(
            "plugin:csd-minimize:fullscreen_command",
            "Command when a CSD fullscreen button is pressed (native fullscreen suppressed when set)",
            "");

        for (auto& w : g_pCompositor->m_windows) {
            if (w && w->m_isMapped && !w->isHidden())
                registerWindow(w);
        }

        m_windowOpenListener = Event::bus()->m_events.window.open.listen([this](PHLWINDOW w) { registerWindow(w); });

        m_configReloadListener = Event::bus()->m_events.config.reloaded.listen([this]() {
            for (auto& w : g_pCompositor->m_windows) {
                if (w && w->m_isMapped && !w->isHidden())
                    applySuppression(w);
            }
        });

        m_windowDestroyListener = Event::bus()->m_events.window.destroy.listen([this](PHLWINDOWREF w) {
            if (auto pWindow = w.lock())
                unregisterWindow(pWindow.get());
        });
    }

    void exit() {
        m_windows.clear();
        m_windowOpenListener.reset();
        m_windowDestroyListener.reset();
        m_configReloadListener.reset();
    }

  private:
    struct SSuppressState {
        bool maximize   = false;
        bool fullscreen = false;
    };

    struct SWindowState {
        CHyprSignalListener stateChanged;
        SSuppressState      suppress;
        bool                listening = false;
    };

    HANDLE                           m_handle = nullptr;
    SP<Config::Values::CStringValue> m_minimizeCommandVal;
    SP<Config::Values::CStringValue> m_maximizeCommandVal;
    SP<Config::Values::CStringValue> m_unmaximizeCommandVal;
    SP<Config::Values::CStringValue> m_fullscreenCommandVal;
    std::unordered_map<Desktop::View::CWindow*, SWindowState> m_windows;
    CHyprSignalListener              m_windowOpenListener;
    CHyprSignalListener              m_windowDestroyListener;
    CHyprSignalListener              m_configReloadListener;

    SP<Config::Values::CStringValue> addCommand(const char* key, const char* description, const char* fallback) {
        auto value = makeShared<Config::Values::CStringValue>(key, description, fallback);
        HyprlandAPI::addConfigValueV2(m_handle, value);
        return value;
    }

    void runCommandFor(PHLWINDOW pWindow, const std::string& base, bool withCursor = false) {
        if (!pWindow || base.empty() || base == "true")
            return;
        // Append address (+ cursor at event time): system()/exec is async, so
        // ventanas must not re-query cursorpos after the pointer has moved.
        std::string cmd;
        if (withCursor && g_pInputManager) {
            const auto mouse = g_pInputManager->getMouseCoordsInternal();
            cmd = std::format("{} 0x{:x} {:.0f} {:.0f}", base, reinterpret_cast<uintptr_t>(pWindow.get()), mouse.x,
                              mouse.y);
        } else {
            cmd = std::format("{} 0x{:x}", base, reinterpret_cast<uintptr_t>(pWindow.get()));
        }
        std::thread([cmd]() { system(cmd.c_str()); }).detach();
    }

    void handleMaximizeRequest(PHLWINDOW pWindow, bool wantMax) {
        // set_maximized → ensure max (idempotent). unset_maximized → shrink.
        // Never route both through a toggle: Chrome sends set_maximized on map
        // and that would undo ventanas auto-max / re-expand after □.
        // Pass cursor so □ hit-test survives async exec.
        if (wantMax)
            runCommandFor(pWindow, m_maximizeCommandVal->value(), true);
        else
            runCommandFor(pWindow, m_unmaximizeCommandVal->value(), true);
    }

    void handleState(PHLWINDOW pWindow, bool minimize, bool fullscreen) {
        if (!pWindow)
            return;
        if (minimize)
            runCommandFor(pWindow, m_minimizeCommandVal->value());
        if (fullscreen)
            runCommandFor(pWindow, m_fullscreenCommandVal->value());
    }

    void applySuppression(const PHLWINDOW& pWindow) {
        if (!pWindow)
            return;

        // Only suppress when we actually run a replacement command. Empty
        // maximize/unmaximize → native Hyprland mode-1 maximize (under Jugoo).
        // Always assign bits (do not diff against previous): a rebuilt plugin
        // must clear stale SUPPRESS_MAXIMIZE left by an older maximize_command.
        const bool wantMax = !m_maximizeCommandVal->value().empty() || !m_unmaximizeCommandVal->value().empty();
        const bool wantFs  = !m_fullscreenCommandVal->value().empty();

        uint64_t& flags = pWindow->m_suppressedEvents;
        flags = wantMax ? (flags | Desktop::View::SUPPRESS_MAXIMIZE) : (flags & ~Desktop::View::SUPPRESS_MAXIMIZE);
        flags = wantFs ? (flags | Desktop::View::SUPPRESS_FULLSCREEN) : (flags & ~Desktop::View::SUPPRESS_FULLSCREEN);

        m_windows[pWindow.get()].suppress = SSuppressState{wantMax, wantFs};
    }

    void registerWindow(PHLWINDOW pWindow) {
        if (!pWindow)
            return;

        applySuppression(pWindow);

        SWindowState& state = m_windows[pWindow.get()];
        if (state.listening)
            return;

        const PHLWINDOWREF pWindowRef = pWindow;

        const auto xdg      = pWindow->m_xdgSurface.lock();
        const auto toplevel = xdg ? xdg->m_toplevel.lock() : nullptr;
        if (toplevel) {
            state.stateChanged = toplevel->m_events.stateChanged.listen([this, pWindowRef]() {
                auto pWindow = pWindowRef.lock();
                if (!pWindow)
                    return;
                auto xdg = pWindow->m_xdgSurface.lock();
                if (!xdg)
                    return;
                auto toplevel = xdg->m_toplevel.lock();
                if (!toplevel)
                    return;
                // Volatile one-shot requests: read value then Hyprland resets.
                const bool minReq = toplevel->m_state.requestsMinimize.value_or(false);
                if (auto maxReq = toplevel->m_state.requestsMaximize)
                    handleMaximizeRequest(pWindow, *maxReq);
                const bool fsReq = toplevel->m_state.requestsFullscreen.has_value();
                handleState(pWindow, minReq, fsReq);
            });
            state.listening = true;
            return;
        }

        const auto xwayland = pWindow->m_xwaylandSurface.lock();
        if (xwayland) {
            state.stateChanged = xwayland->m_events.stateChanged.listen([this, pWindowRef]() {
                auto pWindow = pWindowRef.lock();
                if (!pWindow)
                    return;
                auto xwayland = pWindow->m_xwaylandSurface.lock();
                if (!xwayland)
                    return;

                const bool minimize = xwayland->m_state.requestsMinimize.value_or(false);
                const auto maxOpt   = xwayland->m_state.requestsMaximize;
                const bool fullscreen = xwayland->m_state.requestsFullscreen.has_value();

                if (minimize) {
                    xwayland->m_state.requestsMinimize.reset();
                    xwayland->setMinimized(false);
                }
                if (maxOpt) {
                    const bool wantMax = *maxOpt;
                    xwayland->m_state.requestsMaximize.reset();
                    handleMaximizeRequest(pWindow, wantMax);
                }
                if (fullscreen)
                    xwayland->m_state.requestsFullscreen.reset();

                handleState(pWindow, minimize, fullscreen);
            });
            state.listening = true;
        }
    }

    void unregisterWindow(Desktop::View::CWindow* w) {
        m_windows.erase(w);
    }
};

inline UP<CCSDMinimizePlugin> g_pCSDMinimizePlugin;

// Do NOT change these export names — Hyprland 0.55 loads PLUGIN_*.
APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    const std::string HASH        = __hyprland_api_get_hash();
    const std::string CLIENT_HASH = __hyprland_api_get_client_hash();
    if (HASH != CLIENT_HASH) {
        HyprlandAPI::addNotification(handle, "[csd-minimize] Version mismatch (headers != running Hyprland)", CHyprColor{1.0, 0.2, 0.2, 1.0}, 5000);
        throw std::runtime_error("[csd-minimize] Version mismatch");
    }

    g_pCSDMinimizePlugin = makeUnique<CCSDMinimizePlugin>();
    g_pCSDMinimizePlugin->init(handle);

    return {"csd-minimize", "Route CSD minimize/maximize buttons to ventanas", "AidyCOS", "1.1"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    if (g_pCSDMinimizePlugin)
        g_pCSDMinimizePlugin->exit();
    g_pCSDMinimizePlugin.reset();
}
