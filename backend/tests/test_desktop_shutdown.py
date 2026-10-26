"""Exit must finish the ASGI lifespan before releasing the instance lock."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import desktop


def test_shutdown_requests_server_exit_and_waits_for_cleanup():
    lifecycle = desktop.BackendLifecycle()
    server = SimpleNamespace(should_exit=False)
    lifecycle.server = server
    cleaned = threading.Event()

    def serve():
        while not lifecycle.stop_requested.wait(0.01):
            pass
        assert server.should_exit
        cleaned.set()

    lifecycle.thread = threading.Thread(target=serve)
    lifecycle.thread.start()
    assert lifecycle.stop(timeout=1)
    assert cleaned.is_set()
    assert not lifecycle.thread.is_alive()
    assert lifecycle.stop(timeout=1)  # repeated close is harmless


def test_stop_before_server_is_published_is_remembered():
    lifecycle = desktop.BackendLifecycle()
    assert lifecycle.stop(timeout=0.01)
    assert lifecycle.stop_requested.is_set()
    server = SimpleNamespace(should_exit=False)
    assert not lifecycle.attach_server(server)
    assert server.should_exit


def test_shutdown_timeout_is_not_reported_as_success():
    lifecycle = desktop.BackendLifecycle()
    lifecycle.thread = Mock()
    lifecycle.thread.is_alive.return_value = True
    assert lifecycle.stop(timeout=0.01) is False


@pytest.mark.parametrize('window_error', [None, RuntimeError('window failed')])
def test_main_stops_backend_before_unlock_even_on_window_failure(monkeypatch, window_error):
    order = []
    lifecycle = Mock()
    lifecycle.stop.side_effect = lambda: order.append('stop') or True
    monkeypatch.setattr(desktop, 'BackendLifecycle', lambda: lifecycle)
    for name in ('_guard_streams', '_setup_logging', '_ensure_data_dir_writable'):
        monkeypatch.setattr(desktop, name, lambda: None)
    monkeypatch.setattr(desktop, '_acquire_single_instance', lambda: True)
    monkeypatch.setattr(desktop, '_find_free_port', lambda *_: 3018)
    monkeypatch.setattr(desktop, '_wait_for_server', lambda *a, **k: True)
    monkeypatch.setattr(desktop, '_release_single_instance', lambda: order.append('unlock'))
    monkeypatch.setattr(desktop, '_show_crash', lambda *a: None)

    def window(_):
        order.append('window')
        if window_error:
            raise window_error

    monkeypatch.setattr(desktop, '_open_window', window)
    assert desktop.main() == (1 if window_error else 0)
    assert order == ['window', 'stop', 'unlock']


def test_start_timeout_still_stops_backend(monkeypatch):
    lifecycle = Mock()
    lifecycle.stop.return_value = True
    monkeypatch.setattr(desktop, 'BackendLifecycle', lambda: lifecycle)
    for name in ('_guard_streams', '_setup_logging', '_ensure_data_dir_writable'):
        monkeypatch.setattr(desktop, name, lambda: None)
    monkeypatch.setattr(desktop, '_acquire_single_instance', lambda: True)
    monkeypatch.setattr(desktop, '_find_free_port', lambda *_: 3018)
    monkeypatch.setattr(desktop, '_wait_for_server', lambda *a, **k: False)
    unlock = Mock()
    monkeypatch.setattr(desktop, '_release_single_instance', unlock)
    assert desktop.main() == 1
    lifecycle.stop.assert_called_once()
    unlock.assert_called_once()


def test_real_asgi_lifespan_finishes_and_listen_socket_is_released(monkeypatch):
    import socket
    import sys
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    cleaned = threading.Event()

    @asynccontextmanager
    async def lifespan(_app):
        yield
        cleaned.set()

    app = FastAPI(lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    monkeypatch.setitem(sys.modules, 'app.main', SimpleNamespace(app=app))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    lifecycle = desktop.BackendLifecycle()
    lifecycle.start(port)
    try:
        assert desktop._wait_for_server(port, timeout=10)
    finally:
        assert lifecycle.stop(timeout=10)
    assert cleaned.is_set()
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', port)) != 0
