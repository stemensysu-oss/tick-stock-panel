"""Desktop downloads and browser preferences must survive normal app restarts."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import config, desktop


@pytest.fixture
def webview_stub(monkeypatch):
    from app import desktop_macos

    monkeypatch.setattr(desktop_macos, "install_quit_handler", Mock())
    stub = SimpleNamespace(
        settings={"ALLOW_DOWNLOADS": False},
        create_window=Mock(),
        start=Mock(),
    )
    monkeypatch.setitem(sys.modules, "webview", stub)
    return stub


def test_window_keeps_profile_in_configured_data_dir_and_allows_exports(
    tmp_path, monkeypatch, webview_stub
):
    data_dir = tmp_path / "custom-data"
    monkeypatch.setattr(config.settings, "data_dir", data_dir)

    desktop._open_window("http://127.0.0.1:3018")

    options = webview_stub.start.call_args.kwargs
    assert options["private_mode"] is False
    profile = Path(options["storage_path"])
    assert profile.parent == data_dir
    assert profile.is_dir()
    assert webview_stub.settings["ALLOW_DOWNLOADS"] is True
    marker = profile / "existing-profile-marker"
    marker.write_text("keep across restarts", encoding="utf-8")

    desktop._open_window("http://127.0.0.1:3018")

    assert Path(webview_stub.start.call_args.kwargs["storage_path"]) == profile
    assert marker.read_text(encoding="utf-8") == "keep across restarts"
    assert webview_stub.create_window.call_count == 2


def test_window_does_not_replace_an_unusable_profile_with_temporary_storage(
    tmp_path, monkeypatch, webview_stub
):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    profile = tmp_path / "webview"
    profile.write_text("existing user file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        desktop._open_window("http://127.0.0.1:3018")

    assert profile.read_text(encoding="utf-8") == "existing user file"
    webview_stub.create_window.assert_not_called()
    webview_stub.start.assert_not_called()


def test_profile_permission_failure_is_reported_before_opening_window(
    tmp_path, monkeypatch, webview_stub
):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)

    def deny_profile_creation(self, *args, **kwargs):
        raise PermissionError("profile directory is not writable")

    monkeypatch.setattr(Path, "mkdir", deny_profile_creation)

    with pytest.raises(PermissionError, match="profile directory is not writable"):
        desktop._open_window("http://127.0.0.1:3018")

    webview_stub.create_window.assert_not_called()
    webview_stub.start.assert_not_called()
