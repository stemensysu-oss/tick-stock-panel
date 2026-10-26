"""Exercise real Cocoa exit commands on CI-owned processes, never force success."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def diagnostic_files():
    roots = [Path.home() / 'Library/Logs/DiagnosticReports', Path('/Library/Logs/DiagnosticReports')]
    return {p for root in roots if root.is_dir() for p in root.glob('*') if p.suffix in {'.ips', '.crash'}}


def request_exit(child, method, window):
    import AppKit
    import Quartz

    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(child.pid)
    if app is None:
        raise RuntimeError('CI-owned application disappeared before exit command')
    app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.5)
    if method == 'system_quit':
        if not app.terminate():  # macOS Quit request, not SIGTERM/forceTerminate
            raise RuntimeError('macOS rejected normal Quit request')
    elif method == 'command_q':
        for pressed in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, 12, pressed)
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPostToPid(child.pid, event)
    elif method == 'window_close':
        foreground = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if foreground is None or foreground.processIdentifier() != child.pid:
            raise RuntimeError('Refusing to click: the CI-owned app is not foreground')
        bounds = window['kCGWindowBounds']
        position = (bounds['X'] + 14, bounds['Y'] + 14)
        # Title-bar traffic lights are dispatched by WindowServer. PostToPid
        # bypasses its hit testing and does not activate the native close button.
        for event_type in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            event = Quartz.CGEventCreateMouseEvent(None, event_type, position, Quartz.kCGMouseButtonLeft)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(0.1)
    else:
        raise ValueError(method)


def verify_exit(child, method, window, data, base, logs, *, require_cleanup=True):
    before = diagnostic_files()
    desktop_log = data / 'desktop.log'
    prior_log = desktop_log.read_text(encoding='utf8', errors='replace') if desktop_log.exists() else ''
    started = time.monotonic()
    request_exit(child, method, window)
    try:
        code = child.wait(timeout=65)
    except subprocess.TimeoutExpired:
        code = None
    # ReportCrash writes asynchronously; retain evidence even for a zero exit.
    time.sleep(8)
    crashes = []
    for path in diagnostic_files() - before:
        text = path.read_text(encoding='utf8', errors='replace')
        if re.search(r'"pid"\s*:\s*' + str(child.pid) + r'\b', text) or f'[{child.pid}]' in text or path.name.startswith('TSP-'):
            destination = logs.parent / (logs.stem + '-' + path.name)
            destination.write_text(text, encoding='utf8')
            crashes.append(destination.name)
    text = desktop_log.read_text(encoding='utf8', errors='replace') if desktop_log.exists() else ''
    text = text[len(prior_log):]
    closed = 'desktop backend shutdown completed' in text and 'desktop exit completed: code=0' in text
    reachable = False
    try:
        with build_opener(ProxyHandler({})).open(base + '/health', timeout=2) as response:
            reachable = response.status == 200
    except OSError:
        pass
    result = {'method': method, 'exit_code': code, 'elapsed_seconds': round(time.monotonic()-started, 2),
              'backend_cleanup_completed': closed, 'instance_lock_removed': not (data/'.desktop.lock').exists(),
              'health_stopped': not reachable, 'crash_reports': crashes}
    result['passed'] = code == 0 and not reachable and not crashes and (
        not require_cleanup or (closed and result['instance_lock_removed']))
    logs.with_suffix('.exit.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    return result
