"""Mount/copy/launch an actual DMG twice on an ephemeral macOS Actions runner.

Never run on a user's Mac: requires CI, isolated runner temp and DATA_DIR.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import suppress
from pathlib import Path

import psutil
from windows_installer_smoke import check_api, check_live_api, clean_environment, require
from write_build_record import file_sha256
from macos_exit_check import verify_exit


def stop(child):
    with suppress(psutil.NoSuchProcess):
        process = psutil.Process(child.pid)
        processes = [*process.children(recursive=True), process]
        for item in reversed(processes):
            with suppress(psutil.NoSuchProcess):
                item.terminate()
        _, alive = psutil.wait_procs(processes, timeout=10)
        for item in alive:
            with suppress(psutil.NoSuchProcess):
                item.kill()
        _, alive = psutil.wait_procs(alive, timeout=5)
        require(not alive, 'The smoke application did not stop')


def run_app(app, data, work, version, log, exit_method='command_q', check_live=True):
    import Quartz

    with log.open('w', encoding='utf8') as output:
        child = subprocess.Popen([str(app / 'Contents/MacOS/TSP')], cwd=work,
            env=clean_environment(data, work), stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 180
            ready = None
            base = None
            while time.monotonic() < deadline:
                require(child.poll() is None, f'Mac app exited: {child.returncode}; see desktop.log')
                windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
                owned = [window for window in windows if window.get('kCGWindowOwnerPID') == child.pid
                    and window.get('kCGWindowLayer') == 0 and window.get('kCGWindowBounds', {}).get('Width', 0) > 100]
                if base is None:
                    for port in range(3018, 3068):
                        candidate = f'http://127.0.0.1:{port}'
                        try:
                            check_api(candidate, version)
                            base = candidate
                            break
                        except Exception:  # noqa: BLE001 -- bounded health polling
                            continue
                if base and owned:
                    ready = ready or time.monotonic()
                    if time.monotonic() - ready >= 10:
                        check_api(base, version)
                        live = check_live_api(base) if check_live else None
                        screenshot = log.with_suffix('.png')
                        capture = subprocess.run(['screencapture', '-x', str(screenshot)], check=False, capture_output=True)
                        exit_result = verify_exit(child, exit_method, owned[0], data, base, log)
                        require(exit_result['passed'], f'Mac graceful exit failed: {exit_result}')
                        return {'visible_window': True, 'health': True, 'window_count': len(owned),
                            'screenshot_saved': capture.returncode == 0 and screenshot.is_file(),
                            'graceful_exit': exit_result,
                            'verified_live_fallback': live}
                else:
                    ready = None
                time.sleep(1)
            raise RuntimeError('Mac app did not expose a visible window and healthy backend within 180 seconds')
        finally:
            if child.poll() is None:
                stop(child)  # Failure cleanup only; never substitutes for passing normal exit.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--logs', type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'darwin' and os.environ.get('GITHUB_ACTIONS') == 'true', 'Only ephemeral macOS Actions runners are supported')
    runner = Path(os.environ['RUNNER_TEMP']).resolve()
    installer = args.installer.resolve(strict=True)
    logs = args.logs.resolve()
    require(logs.is_relative_to(runner), 'Logs must stay in RUNNER_TEMP')
    logs.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tsp-mac-smoke-', dir=runner)).resolve()
    mount, installed, data = work/'mounted', work/'Applications/TSP.app', work/'isolated-data'
    mount.mkdir()
    installed.parent.mkdir()
    data.mkdir()
    sentinel = data/'preserve.txt'
    sentinel.write_text('preserve-external-user-data', encoding='utf8')
    report = {'status': 'failed', 'version': args.version, 'installer_sha256': file_sha256(installer), 'checks': {}}
    attached = False
    try:
        subprocess.run(['hdiutil', 'verify', str(installer)], check=True)
        subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(installer)], check=True)
        attached = True
        source = mount/'TSP.app'
        info = plistlib.loads((source/'Contents/Info.plist').read_bytes())
        require(info['CFBundleShortVersionString'] == args.version, 'DMG app version mismatch')
        require((source/'Contents/MacOS/TSP').is_file(), 'DMG has no app executable')
        require((mount/'Applications').is_symlink(), 'DMG has no Applications drag target')
        subprocess.run(['ditto', str(source), str(installed)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(installed)], check=True)
        report['checks']['dmg_verified'] = True
        report['checks']['first_launch'] = run_app(installed, data, work, args.version, logs/'first-launch.log')
        # Only the CI-owned app is removed. External user data remains in place.
        require(installed.resolve().is_relative_to(work) and installed.name == 'TSP.app', 'Unsafe app replacement path')
        shutil.rmtree(installed)
        subprocess.run(['ditto', str(source), str(installed)], check=True)
        require(sentinel.read_text(encoding='utf8') == 'preserve-external-user-data', 'App replacement deleted external data')
        report['checks']['second_launch'] = run_app(installed, data, work, args.version, logs/'second-launch.log', 'window_close')
        report['checks']['system_quit'] = run_app(installed, data, work, args.version, logs/'system-quit.log', 'system_quit', False)
        require(not report['checks']['first_launch']['verified_live_fallback']['content_typography']['restored'], 'First Mac launch did not use typography defaults')
        require(report['checks']['second_launch']['verified_live_fallback']['content_typography']['restored'], 'Mac replacement did not retain typography settings')
        require(sentinel.read_text(encoding='utf8') == 'preserve-external-user-data', 'Restart deleted external data')
        report['checks']['replacement_preserved_data'] = True
        report['status'] = 'passed'
    except Exception:
        report['failure'] = traceback.format_exc()
        raise
    finally:
        for name in ('desktop.log', 'app.log'):
            if (data/name).is_file():
                shutil.copy2(data/name, logs/name)
        (logs/'smoke-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        if attached:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=False)


if __name__ == '__main__':
    main()
