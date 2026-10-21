"""Verify a real Inno installer and desktop GUI on a disposable Windows runner.

Never executes the build staging tree. Only processes launched by this script
and their observed descendants may be stopped; no taskkill by image name and
no uninstaller (the product uninstaller stops all TSP processes).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import suppress
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

import psutil
from write_build_record import file_sha256


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class ProcessTree:
    """Keep psutil identities (PID + creation time), including orphaned children."""

    def __init__(self, child: subprocess.Popen):
        self.child = child
        self.root = psutil.Process(child.pid)
        self.observed: dict[int, psutil.Process] = {child.pid: self.root}
        self.root.create_time()

    def refresh(self) -> list[psutil.Process]:
        for process in list(self.observed.values()):
            try:
                if process.is_running():
                    for descendant in process.children(recursive=True):
                        descendant.create_time()
                        self.observed.setdefault(descendant.pid, descendant)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return [process for process in self.observed.values() if process.is_running()]

    def stop(self) -> None:
        # Closing the real window lets the normal application release its profile
        # before the second install. A hung/crashed GUI still has bounded cleanup.
        processes = self.refresh()
        for handle, _title in visible_windows({process.pid for process in processes}):
            ctypes.windll.user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE
        _gone, alive = psutil.wait_procs(processes, timeout=5)
        for process in alive:
            with suppress(psutil.NoSuchProcess):
                process.terminate()
        _gone, alive = psutil.wait_procs(alive, timeout=5)
        for process in alive:
            with suppress(psutil.NoSuchProcess):
                process.kill()
        _gone, alive = psutil.wait_procs(alive, timeout=5)
        require(not alive, "A process started by this smoke test could not be stopped")


def visible_windows(pids: set[int]) -> list[tuple[int, str]]:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    windows: list[tuple[int, str]] = []

    @callback_type
    def visit(handle, _context):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(handle):
            title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(handle) + 1)
            user32.GetWindowTextW(handle, title, len(title))
            windows.append((handle, title.value))
        return True

    require(bool(user32.EnumWindows(visit, 0)), "Could not enumerate desktop windows")
    return windows


def run_installer(installer: Path, destination: Path | None, log: Path) -> None:
    command = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={log}"]
    if destination is not None:
        command.append(f"/DIR={destination}")
    child = subprocess.Popen(command, cwd=log.parent)
    tree = ProcessTree(child)
    deadline = time.monotonic() + 300
    try:
        while child.poll() is None and time.monotonic() < deadline:
            tree.refresh()
            time.sleep(0.5)
        require(child.poll() is not None, "Silent installer timed out after 300 seconds")
        require(child.returncode == 0, f"Silent installer failed with exit code {child.returncode}")
    finally:
        tree.stop()


def json_request(base: str, route: str) -> dict:
    # A machine-wide proxy must not send local smoke traffic outside the runner.
    opener = build_opener(ProxyHandler({}))
    with opener.open(base + route, timeout=3) as response:
        require(response.status == 200, f"{route}: expected HTTP 200")
        require(response.headers.get_content_type() == "application/json", f"{route}: not JSON (possibly SPA fallback)")
        result = json.load(response)
    require(isinstance(result, dict), f"{route}: expected a JSON object")
    return result


def check_api(base: str, version: str) -> None:
    health = json_request(base, "/health")
    require(health.get("status") == "ok" and health.get("version") == version, "Wrong application health/version")
    snapshot = json_request(base, "/api/ext/convertibles")
    require(snapshot.get("items") == [] and bool(snapshot.get("revision")), "Convertible extension did not start with an empty snapshot")
    convertibles = json_request(base, "/api/ext/convertibles/status")
    require(convertibles.get("provider") == "tickflow" and convertibles.get("configured") is False, "Unexpected convertible provider/configuration")
    funds = json_request(base, "/api/ext/funds/status")
    require(funds.get("provider") == "fuyao" and funds.get("configured") is False, "Fund extension missing or unexpectedly configured")


def clean_environment(data_dir: Path, cwd: Path) -> dict[str, str]:
    environment = os.environ.copy()
    # Do not inherit developer credentials or an unrelated .env into the test.
    for key in list(environment):
        if key.upper().endswith(("_API_KEY", "_TOKEN")) or key.upper() in {"AUTH_PASSWORD", "TICKFLOW_ENV_FILE", "DATA_DIR"}:
            environment.pop(key)
    environment.update({
        "DATA_DIR": str(data_dir),
        "TICKFLOW_ENV_FILE": str(cwd / "empty.env"),
        "AUTH_PASSWORD": "",
        "TICKFLOW_API_KEY": "",
        "FUYAO_API_KEY": "",
    })
    return environment


def run_desktop(executable: Path, data_dir: Path, cwd: Path, version: str, log: Path) -> dict:
    with log.open("w", encoding="utf-8") as output:
        child = subprocess.Popen(
            [str(executable)], cwd=cwd, env=clean_environment(data_dir, cwd),
            stdout=output, stderr=subprocess.STDOUT,
        )
        tree = ProcessTree(child)
        deadline = time.monotonic() + 150
        last_problem = "No listening backend/main window/WebView2 renderer yet"
        base = None
        gui_ready_at = None
        try:
            while time.monotonic() < deadline:
                processes = tree.refresh()
                require(child.poll() is None, f"Desktop exited early ({child.returncode}); see desktop.log")
                ports: set[int] = set()
                renderer = False
                for process in processes:
                    try:
                        renderer = renderer or process.name().lower() == "msedgewebview2.exe"
                        for connection in process.net_connections(kind="tcp"):
                            if connection.status == psutil.CONN_LISTEN and connection.laddr.ip == "127.0.0.1":
                                ports.add(connection.laddr.port)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                titles = [title for _handle, title in visible_windows({process.pid for process in processes})]
                require(not any("启动失败" in title for title in titles), "Desktop showed its startup error dialog; see desktop.log")
                for port in sorted(ports):
                    candidate = f"http://127.0.0.1:{port}"
                    try:
                        check_api(candidate, version)
                    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                        last_problem = str(exc)
                        continue
                    base = candidate
                    break
                if base and "TSP" in titles and renderer:
                    if gui_ready_at is None:
                        gui_ready_at = time.monotonic()
                    # A health response can precede a failing webview import. Keep
                    # the real GUI/process alive, then repeat the extension checks.
                    if time.monotonic() - gui_ready_at >= 10:
                        check_api(base, version)
                        require((data_dir / "webview").is_dir(), "Persistent WebView profile was not created in DATA_DIR")
                        return {"health": True, "funds_api": True, "convertibles_api": True, "visible_window": True, "webview2": True}
                else:
                    gui_ready_at = None
                    if base:
                        last_problem = f"Backend is ready, but TSP GUI/WebView2 is missing (window={titles!r}, webview2={renderer})"
                time.sleep(0.5)
            raise RuntimeError(f"Desktop smoke timed out after 150 seconds: {last_problem}")
        finally:
            tree.stop()


def staging_inventory(root: Path) -> dict[str, tuple[int, int]]:
    return {str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--logs", type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true", "Installer smoke is restricted to disposable Windows GitHub Actions runners")
    installer = args.installer.resolve(strict=True)
    staging = args.staging.resolve(strict=True)
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    initial_staging = staging_inventory(staging)
    work = Path(tempfile.mkdtemp(prefix="tsp-installer-smoke-", dir=os.environ["RUNNER_TEMP"]))
    install_dir, data_dir = work / "installed", work / "isolated-data"
    require(not work.is_relative_to(staging), "Smoke work directory must not be inside build staging")
    data_dir.mkdir()
    (work / "empty.env").write_text("", encoding="utf-8")
    sentinel = "keep-this-user-data-during-overwrite\n"
    external_sentinel = data_dir / "ci-preserve.txt"
    external_sentinel.write_text(sentinel, encoding="utf-8")
    report = {"status": "failed", "version": args.version, "installer_sha256": file_sha256(installer), "checks": {}}
    try:
        run_installer(installer, install_dir, logs / "install-first.log")
        executable = install_dir / "TSP.exe"
        require(executable.is_file(), "Installer ignored /DIR or did not install TSP.exe")
        require(file_sha256(executable) == file_sha256(staging / "TSP.exe"), "Installed executable differs from the build")
        bundled_version = json.loads((install_dir / "_internal/package.json").read_text(encoding="utf-8"))["version"]
        require(bundled_version == args.version, "Installed resource version is incorrect")
        local_sentinel = install_dir / "data/ci-preserve.txt"
        local_sentinel.parent.mkdir(exist_ok=True)
        local_sentinel.write_text(sentinel, encoding="utf-8")
        report["checks"]["first_launch"] = run_desktop(executable, data_dir, work, args.version, logs / "launch-first.log")
        # A second install to a different directory could leave the old copy
        # runnable. Mark one program resource, then require it to be replaced at
        # this exact remembered path; data sentinels must remain unchanged.
        resource = install_dir / "_internal/package.json"
        resource.write_text('{"version":"smoke-needs-overwrite"}', encoding="utf-8")
        # Deliberately omit /DIR: the upgrade must reuse the remembered path.
        run_installer(installer, None, logs / "install-overwrite.log")
        require(json.loads(resource.read_text(encoding="utf-8"))["version"] == args.version, "Overwrite installation did not reuse the previous install directory")
        require(local_sentinel.read_text(encoding="utf-8") == sentinel, "Overwrite installation changed install-directory user data")
        require(external_sentinel.read_text(encoding="utf-8") == sentinel, "Overwrite installation changed isolated DATA_DIR")
        report["checks"]["overwrite_preserves_data"] = True
        report["checks"]["overwrite_reuses_directory"] = True
        report["checks"]["second_launch"] = run_desktop(executable, data_dir, work, args.version, logs / "launch-second.log")
        require(staging_inventory(staging) == initial_staging, "Smoke test modified build staging")
        report["checks"]["staging_untouched"] = True
        report["status"] = "passed"
    except Exception as exc:
        report["error"] = str(exc)
        (logs / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        for name in ("desktop.log", "backend.log"):
            if (data_dir / name).is_file():
                shutil.copy2(data_dir / name, logs / name)
        (logs / "smoke-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        # Never run the product uninstaller or delete any path outside this
        # freshly created temporary directory. The runner discards its registry.
        shutil.rmtree(work, ignore_errors=True)
    print("Windows installation, real GUI, extension APIs and overwrite checks passed")


if __name__ == "__main__":
    main()
