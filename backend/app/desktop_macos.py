"""Route Cocoa Quit through window close and Python's normal shutdown path.

pywebview 6.2.1's default AppDelegate returns NSTerminateNow for Cmd-Q.
NSApplication then exits inside the native event loop, bypassing desktop.main's
finally block. Retain a dedicated delegate and cancel native termination while
dispatching performClose: on the next main-loop turn. This preserves closing
vetoes, WKWebView teardown and webview.start returning to our backend cleanup.
The small adapter is macOS-only; revisit it when upgrading pywebview.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_delegate = None  # Keep the ObjC/Python delegate alive through callback return.


class QuitCoordinator:
    def __init__(self, schedule, windows):
        self.schedule = schedule
        self.windows = windows
        self.pending = False

    def request(self):
        if not self.pending:
            self.pending = True
            self.schedule(self.close_windows)
        return 0  # NSTerminateCancel: do not exit underneath the Python runtime.

    def close_windows(self):
        try:
            for window in list(self.windows()):
                window.performClose_(None)  # Calls windowShouldClose_, including vetoes.
        finally:
            self.pending = False


def install_quit_handler() -> None:
    global _delegate
    if _delegate is not None:
        return

    from PyObjCTools import AppHelper
    from webview.platforms import cocoa

    coordinator = QuitCoordinator(
        AppHelper.callAfter,
        lambda: [view.window for view in cocoa.BrowserView.instances.values()],
    )

    class TSPApplicationDelegate(cocoa.BrowserView.AppDelegate):
        def applicationShouldTerminate_(self, _app):  # noqa: N802
            logger.info("macOS quit requested; routing through window close")
            return coordinator.request()

    _delegate = TSPApplicationDelegate.alloc().init()
    cocoa.BrowserView._shared_app_delegate = _delegate
