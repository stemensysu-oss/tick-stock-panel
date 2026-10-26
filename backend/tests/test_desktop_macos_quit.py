"""Native Quit is deferred, never immediate process termination."""
from unittest.mock import Mock

from app.desktop_macos import QuitCoordinator


def test_quit_cancels_native_termination_then_closes_on_main_loop():
    scheduled = []
    window = Mock()
    coordinator = QuitCoordinator(scheduled.append, lambda: [window])
    assert coordinator.request() == 0
    window.performClose_.assert_not_called()
    assert coordinator.request() == 0
    assert len(scheduled) == 1
    scheduled.pop()()
    window.performClose_.assert_called_once_with(None)
    assert not coordinator.pending


def test_vetoed_window_can_receive_another_quit_request():
    scheduled = []
    window = Mock()  # Native windowShouldClose decides whether it closes.
    coordinator = QuitCoordinator(scheduled.append, lambda: [window])
    coordinator.request()
    scheduled.pop()()
    coordinator.request()
    scheduled.pop()()
    assert window.performClose_.call_count == 2


def test_window_list_is_copied_before_native_close_mutates_it():
    scheduled, windows = [], []
    window = Mock()
    window.performClose_.side_effect = lambda _: windows.clear()
    windows.append(window)
    coordinator = QuitCoordinator(scheduled.append, lambda: windows)
    coordinator.request()
    scheduled.pop()()
    assert not windows
