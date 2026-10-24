"""Finder-like PATH regression tests; no actual account or AI requests."""

from pathlib import Path

import pytest

from app.services import ai_provider


@pytest.fixture
def mac_runtime(monkeypatch, tmp_path):
    from app.services import codex_macos

    monkeypatch.setattr(ai_provider.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setattr(ai_provider.shutil, "which", lambda command: None)
    monkeypatch.setattr(codex_macos, "SYSTEM_BIN_DIRS", ())
    monkeypatch.setattr(codex_macos, "SYSTEM_DESKTOP_APPS", ())
    monkeypatch.setattr(ai_provider, "current_codex_command", lambda: "codex")
    return codex_macos, tmp_path


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test stub, never executed", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    "install",
    [
        ".local/bin",
        ".npm-global/bin",
        ".volta/bin",
        ".nvm/versions/node/v22.14.0/bin",
        "Library/Application Support/fnm/node-versions/v22.14.0/installation/bin",
    ],
)
def test_finder_path_finds_installed_cli(mac_runtime, install):
    _, home = mac_runtime
    target = executable(home / install / "codex")
    assert ai_provider._resolve_command("codex") == str(target)


def test_homebrew_and_desktop_locations(mac_runtime, monkeypatch):
    module, home = mac_runtime
    brew = home / "homebrew/bin"
    target = executable(brew / "codex")
    monkeypatch.setattr(module, "SYSTEM_BIN_DIRS", (brew,))
    assert ai_provider._resolve_command("codex") == str(target)
    target.unlink()
    app = home / "Applications/Codex.app"
    target = executable(app / "Contents/Resources/codex")
    assert ai_provider._resolve_command("codex") == str(target)


def test_version_and_exec_share_node_path(mac_runtime, monkeypatch):
    _, home = mac_runtime
    target = executable(home / ".nvm/versions/node/v22.14.0/bin/codex")
    original = ai_provider.os.environ["PATH"]
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return type("Completed", (), dict(returncode=0, stdout=b"codex-cli test", stderr=b""))()

    monkeypatch.setattr(ai_provider.subprocess, "run", run)
    assert ai_provider.codex_cli_available()
    ai_provider._run_codex_process(
        [str(target), "exec"], "test", {"PATH": original, "CODEX_HOME": "test-home"}, 1
    )
    for _, kwargs in calls:
        assert kwargs["env"]["PATH"].split(ai_provider.os.pathsep)[0] == str(target.parent)
    assert ai_provider.os.environ["PATH"] == original


def test_path_command_retains_priority_and_custom_commands_rejected(mac_runtime, monkeypatch):
    monkeypatch.setattr(ai_provider.shutil, "which", lambda cmd: "/custom/bin/codex")
    assert ai_provider._resolve_command("codex") == "/custom/bin/codex"
    assert ai_provider._resolve_command("/tmp/arbitrary-command") is None
    assert ai_provider._resolve_command("codex; echo hi") is None


def test_empty_missing_or_non_executable_candidates_not_accepted(mac_runtime, monkeypatch):
    module, home = mac_runtime
    assert ai_provider._resolve_command("codex") is None
    (home / ".local/bin/codex").mkdir(parents=True)
    assert ai_provider._resolve_command("codex") is None
    target = executable(home / ".npm-global/bin/codex")
    monkeypatch.setattr(module.os, "access", lambda path, mode: False)
    assert target.is_file()
    assert ai_provider._resolve_command("codex") is None
