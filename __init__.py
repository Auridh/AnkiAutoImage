from __future__ import annotations

"""
Anki add-on: Auto Images

Adds two entry points:
- Tools -> Auto Images
- Browser -> Edit -> Auto Images

Configuration is read from config.json next to this file.
"""

# Ensure vendored dependencies are importable
try:
    import os, sys
    _base_dir = os.path.dirname(__file__)
    _vendor = os.path.join(_base_dir, "vendor")
    if os.path.isdir(_vendor) and _vendor not in sys.path:
        sys.path.insert(0, _vendor)
except Exception:
    pass

from aqt import mw
from aqt.qt import QAction, QKeySequence, QShortcut, qconnect, Qt


def _open_tools_dialog() -> None:
    from .tools import BackfillImagesDialog
    dialog = BackfillImagesDialog(mw=mw, mode="deck", browser=None)
    dialog.exec()


def _open_browser_dialog(browser) -> None:
    from .tools import BackfillImagesDialog
    dialog = BackfillImagesDialog(mw=mw, mode="browser", browser=browser)
    dialog.exec()


def _setup_tools_menu() -> None:
    action = QAction("Auto Images", mw)
    qconnect(action.triggered, _open_tools_dialog)
    mw.form.menuTools.addAction(action)


def _setup_browser_menu_with_gui_hooks() -> bool:
    try:
        from aqt import gui_hooks

        def on_browser_menus_init(browser):
            action = QAction("Auto Images", browser)
            qconnect(action.triggered, lambda: _open_browser_dialog(browser))
            browser.form.menuEdit.addAction(action)

        def on_browser_context_menu(browser, menu):
            action = QAction("Auto Images", browser)
            qconnect(action.triggered, lambda: _open_browser_dialog(browser))
            menu.addSeparator()
            menu.addAction(action)

        gui_hooks.browser_menus_did_init.append(on_browser_menus_init)
        # Right-click context menu entry
        try:
            gui_hooks.browser_will_show_context_menu.append(on_browser_context_menu)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _setup_browser_menu_with_legacy_hook() -> None:
    try:
        from anki.hooks import addHook

        def on_browser_setup_menus(browser):
            action = QAction("Auto Images", browser)
            qconnect(action.triggered, lambda: _open_browser_dialog(browser))
            browser.form.menuEdit.addAction(action)
            # Context menu on older Anki (fallback)
            try:
                menu = browser.form.menuEdit
                menu.addSeparator()
                menu.addAction(action)
            except Exception:
                pass

        addHook("browser.setupMenus", on_browser_setup_menus)
    except Exception:
        # Best-effort; older/newer Anki APIs may vary.
        pass


def init_addon() -> None:
    _setup_tools_menu()
    if not _setup_browser_menu_with_gui_hooks():
        _setup_browser_menu_with_legacy_hook()

    # Reviewer hotkey (configurable via config.json -> reviewer_hotkey)
    try:
        import json, os
        base_dir = os.path.dirname(__file__)
        cfg_path = os.path.join(base_dir, "config.json")
        hotkey = "Ctrl+Shift+G"

		# logging dir
        os.makedirs(os.path.join(base_dir, 'logs'), exist_ok=True)
        
        try:
            # Prefer Anki-managed config from meta.json
            try:
                pkg = os.path.basename(os.path.dirname(__file__))
                cfg = mw.addonManager.getConfig(pkg) or {}
            except Exception:
                cfg = {}

            # Fallback to bundled config.json
            if not cfg:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                hotkey = str(cfg.get("reviewer_hotkey", hotkey)) or hotkey
        except Exception:
            pass

        sc = QShortcut(QKeySequence(hotkey), mw)
        from .tools import quick_add_nadeshiko_for_current_card
        qconnect(sc.activated, lambda: quick_add_nadeshiko_for_current_card(mw))    
        
        # Ensure shortcuts are global within the app window
        try:
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        except Exception:
            pass

        # Keep references to prevent garbage collection
        try:
            if not hasattr(mw, "_autoimage_shortcuts"):
                mw._autoimage_shortcuts = [] # pyright: ignore
            mw._autoimage_shortcuts.extend([sc]) # pyright: ignore
        except Exception:
            pass
    except Exception:
        pass


# Initialize on import
init_addon()


