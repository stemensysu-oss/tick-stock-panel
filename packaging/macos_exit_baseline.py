"""Observe the old desktop entry point's real Cmd-Q path on an isolated CI Mac.

Not an installer claim: source entry point + current locked dependencies/assets.
The baseline is pinned, read with git show; never executes remote arbitrary code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from macos_exit_check import verify_exit
from macos_installer_smoke import stop
from windows_installer_smoke import check_api, clean_environment, require


def probe(entry, label, method, logs, root, *, strict):
    import Quartz

    work = Path(tempfile.mkdtemp(prefix='tsp-old-exit-', dir=os.environ['RUNNER_TEMP']))
    data = work / 'data'
    data.mkdir()
    env = clean_environment(data, work)
    env['PYTHONPATH'] = str(root / 'backend')
    version = json.loads((root/'frontend/package.json').read_text())['version']
    log = logs / (label + '.log')
    with log.open('w') as output:
        child = subprocess.Popen([sys.executable, str(entry)], cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                require(child.poll() is None, 'Baseline failed to start')
                windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
                owned = [w for w in windows if w.get('kCGWindowOwnerPID') == child.pid and w.get('kCGWindowLayer') == 0
                         and w.get('kCGWindowBounds', {}).get('Width', 0) > 100]
                if owned:
                    for port in range(3018, 3068):
                        base = f'http://127.0.0.1:{port}'
                        try:
                            check_api(base, version)
                        except Exception:  # noqa: BLE001 -- bounded polling
                            continue
                        time.sleep(5)
                        result = verify_exit(child, method, owned[0], data, base, log)
                        print(label + '=' + json.dumps(result), flush=True)
                        if strict:
                            require(result['passed'], f'Source exit probe failed: {result}')
                        return
                time.sleep(1)
            raise RuntimeError('Baseline window/health did not become ready')
        finally:
            if child.poll() is None:
                stop(child)
            if (data/'desktop.log').exists():
                (logs/(label + '-desktop.log')).write_bytes((data/'desktop.log').read_bytes())


def main():
    require(sys.platform == 'darwin' and os.environ.get('GITHUB_ACTIONS') == 'true', 'CI Mac only')
    logs = Path(os.environ['RUNNER_TEMP']) / 'tsp-mac-baseline-logs'
    logs.mkdir(exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    old = subprocess.check_output(['git', 'show', 'fda62b66db13859d25c6130e4c7f3832281bbec1:backend/app/desktop.py'], cwd=root)
    entry = logs / 'old_desktop.py'
    entry.write_bytes(old)
    probe(entry, 'baseline', 'command_q', logs, root, strict=False)
    for method in ('window_close', 'system_quit', 'command_q'):
        probe(root/'backend/app/desktop.py', 'fixed-' + method, method, logs, root, strict=True)


if __name__ == '__main__':
    main()
