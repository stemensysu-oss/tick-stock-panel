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
from urllib.request import ProxyHandler, Request, build_opener

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


def json_request(base: str, route: str, *, body=None, timeout=3) -> dict:
    # A machine-wide proxy must not send local smoke traffic outside the runner.
    opener = build_opener(ProxyHandler({}))
    request = Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    try:
        with opener.open(request, timeout=timeout) as response:
            require(response.status == 200, f"{route}: expected HTTP 200")
            require(response.headers.get_content_type() == "application/json", f"{route}: not JSON (possibly SPA fallback)")
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(2048).decode('utf-8', errors='replace')
        raise RuntimeError(f'{route}: HTTP {exc.code}; {detail}') from None
    require(isinstance(result, dict), f"{route}: expected a JSON object")
    return result


def check_api(base: str, version: str) -> None:
    health = json_request(base, "/health")
    require(health.get("status") == "ok" and health.get("version") == version, "Wrong application health/version")
    snapshot = json_request(base, "/api/ext/convertibles")
    require(isinstance(snapshot.get("items"), list) and bool(snapshot.get("revision")), "Convertible extension snapshot is invalid")
    convertibles = json_request(base, "/api/ext/convertibles/status")
    require(convertibles.get("provider") == "tickflow_fuyao_eastmoney" and convertibles.get("configured") is True, "Convertible fallback path is unavailable")
    funds = json_request(base, "/api/ext/funds/status")
    require(funds.get("provider") == "fuyao_then_eastmoney" and funds.get("configured") is True, "Fund fallback path is unavailable")


def check_hk_watchlist(base: str) -> dict:
    """Exercise the exact main-watchlist entry reported by the user."""
    from urllib.parse import urlencode
    searches = {}
    for keyword in ('00700', '腾讯', '腾讯科技', '香港兴业'):
        data = json_request(base, '/api/kline/instruments/search?' + urlencode({
            'q': keyword, 'asset_types': 'stock,etf,index,hk', 'limit': 20}), timeout=120)
        expected = '00480.HK' if keyword == '香港兴业' else '00700.HK'
        require(any(row['symbol'] == expected and row['asset_type'] == 'hk'
                    for row in data['results']), f'Main watchlist HK search failed: {keyword}')
        if keyword == '00700':
            require(all(row['symbol'] == '00700.HK' for row in data['results']),
                    '00700 silently substituted mainland substring matches')
        searches[keyword] = data
    groups = json_request(base, '/api/watchlist/groups')['groups']
    group = next((row for row in groups if row['name'] == '港股云端验证'), None)
    if group is None:
        group = json_request(base, '/api/watchlist/groups', body={'name': '港股云端验证'})['group']
    listed = json_request(base, '/api/watchlist',
                          body={'symbol': '00700.HK', 'group_id': group['id']})['symbols']
    require(any(row['symbol'] == '00700.HK' and group['id'] in row['group_ids'] for row in listed),
            'HK add to current watchlist group did not persist')
    data = json_request(base, '/api/watchlist/hk-quotes?force=true', timeout=120)
    row = next((row for row in data['rows'] if row['symbol'] == '00700.HK'), {})
    require(row.get('currency') == 'HKD' and (row.get('close') or 0) > 0
            and row.get('quote_at') and row.get('quote_source'), 'HK main watchlist quote is missing')
    enriched = json_request(base, '/api/watchlist/enriched')['rows']
    actual = next((item for item in enriched if item['symbol'] == '00700.HK'), {})
    require(actual.get('asset_type') == 'hk' and actual.get('close') == row['close'],
            'HK quote was lost in main watchlist enriched response')
    require(actual.get('rsi14') is None and actual.get('limit_up_price') is None,
            'HK acquired unsupported mainland technical indicators')
    print(f'Installed main watchlist 00700.HK: {row["close"]} HKD, {row["quote_at"]}', flush=True)
    return {'searches': searches, 'quote': row, 'group_id': group['id']}


def check_hk_analysis(base: str) -> dict:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    query = json_request(base, '/api/kline/instruments/search?' + urlencode({
        'q': '00700', 'asset_types': 'stock,index,hk'}), timeout=120)
    require([r['symbol'] for r in query['results']] == ['00700.HK'], 'Analysis search substituted mainland code')
    data = json_request(base, '/api/stock-analysis/hk-data?symbol=00700.HK&force=true', timeout=120)
    require(data['currency'] == 'HKD' and data['price_basis'] == 'unadjusted', 'HK price basis/currency wrong')
    require(len(data['rows']) == 250 and data['as_of'] == data['rows'][-1]['date'], 'HK history incomplete')
    require(data['levels']['pivot'] and data['levels']['extreme'] and data['levels']['sr'] == [], 'HK levels invalid')
    require(all(r.get('ma20') is not None for r in data['rows'][-20:]), 'HK indicators missing')
    require([a['provider'] for a in data['attempts']] == ['tickflow', 'fuyao', 'tencent_public'], 'HK daily order wrong')
    # This runner has no personal AI credential. A clear error is required;
    # successful model streaming is separately covered by the labelled contract test double.
    request = Request(base + '/api/stock-analysis/analyze', data=json.dumps({'symbol':'00700.HK'}).encode(),
                      headers={'Content-Type':'application/json'})
    with urlopen(request, timeout=90) as response:
        events = [json.loads(line) for line in response.read().decode().splitlines() if line]
    require(any(e['type'] == 'meta' and 'HKD' in e['summary'] for e in events), 'HK AI context missing')
    require(any(e['type'] == 'error' for e in events) and not any(e['type'] == 'done' for e in events),
            'Unconfigured AI was incorrectly represented as a successful report')
    focus = 'CLOUD-TEST-NOT-AI'
    reports = json_request(base, '/api/stock-analysis/reports')['reports']
    saved = next((r for r in reports if r.get('focus') == focus and r['symbol'] == '00700.HK'), None)
    if saved is None:
        saved = json_request(base, '/api/stock-analysis/reports', body={'symbol':'00700.HK',
            'name':'腾讯控股', 'focus':focus, 'content':'云端报告持久化测试，非AI生成。',
            'summary':f"HKD unadjusted {data['as_of']}", 'close':data['close'], 'levels':data['levels']})['report']
    require(any(r['id'] == saved['id'] for r in json_request(base, '/api/stock-analysis/reports')['reports']),
            'HK report persistence failed')
    print(f"Installed HK analysis 00700.HK: {len(data['rows'])} daily bars, {data['as_of']}, AI missing-key path verified", flush=True)
    return {'symbol':data['symbol'], 'rows':len(data['rows']), 'as_of':data['as_of'],
        'source':data['source'], 'attempts':data['attempts'], 'levels':{k:len(v) for k,v in data['levels'].items()},
        'ai_live_model_verified':False, 'ai_missing_config_verified':True,
        'ai_streaming_contract':'separate cloud test uses labelled test model', 'report_id':saved['id']}


def check_live_api(base: str) -> dict:
    """No credentials. Exercise real public fallback in the INSTALLED application."""
    hk_watchlist = check_hk_watchlist(base)
    hk_analysis = check_hk_analysis(base)
    before = json_request(base, '/api/ext/convertibles')
    bonds = json_request(base, '/api/ext/convertibles/refresh',
                         body={'expected_revision': before['revision']}, timeout=180)
    require(len(bonds['items']) > 100, 'Market discovery/refresh did not return convertible prices')
    require(all(item.get('quote_at') and any(source in item.get('quote_source', '')
                for source in ('eastmoney_public', 'tencent_public'))
                for item in bonds['items']), 'Missing real convertible provenance/time')
    computed = sum(item.get('double_low') is not None for item in bonds['items'])
    require(computed > 100, 'Convertible stock bindings/prices or reference conversion prices are missing')
    result = {'hk_watchlist': hk_watchlist, 'hk_analysis': hk_analysis, 'convertibles': {'rows': len(bonds['items']), 'as_of': bonds['as_of'],
                              'with_double_low': computed}, 'markets': {}}
    print(f'Installed live convertibles: {len(bonds["items"])} rows, {computed} with double-low', flush=True)
    for category in ('etf', 'lof', 'cash', 'reits', 'indices', 'bonds', 'hk'):
        print(f'Checking installed live market: {category}', flush=True)
        data = json_request(base, f'/api/multi-asset/snapshot?category={category}&mode=market&force=true', timeout=180)
        require(len(data['rows']) >= (2 if category == 'cash' else 6), f'{category} market feed is empty')
        require(data['data_status'] == 'market' and all(row.get('source_id') in {'eastmoney_public', 'tencent_public'}
                and row.get('quote_at') for row in data['rows']), f'{category} provenance is invalid')
        require([a['provider'] for a in data['attempts']][:3] == ['tickflow', 'fuyao', 'eastmoney_public']
                and data['attempts'][-1]['status'] == 'success',
                f'{category} fallback order was not recorded')
        result['markets'][category] = {'rows': len(data['rows']), 'attempts': data['attempts']}
        print(f'Installed live market {category}: {len(data["rows"])} rows', flush=True)
        if category == 'hk':
            require(all(row['currency'] == 'HKD' and row['code'].endswith('.HK')
                        for row in data['rows']), 'HK quote currency/code is invalid')
    for category in ('dividends', 'ipo', 'ah', 'qdii'):
        print(f'Checking installed event/qualification dataset: {category}', flush=True)
        data = json_request(base, f'/api/multi-asset/snapshot?category={category}&mode=market&force=true', timeout=240)
        require(bool(data['rows']) and data['data_status'] == 'market', f'{category} dataset is empty')
        require(all(row['data_status'] == 'market' and row.get('source_url') and row.get('as_of')
                    for row in data['rows']), f'{category} dataset provenance is incomplete')
        require(all(not row['code'].startswith('DEMO') for row in data['rows']), f'{category} uses demo records')
        if category == 'dividends':
            require(any(row.get('dividend_per_share') is not None for row in data['rows']), 'Cash dividends missing')
            require(all(row['metrics']['dividend_yield_pct'] is None for row in data['rows']),
                    'Incomplete dividend history was represented as a period yield')
        elif category == 'ipo':
            require(all(row.get('event_date') and row.get('subscription_status') for row in data['rows']),
                    'IPO application dates/status missing')
        elif category == 'ah':
            require(any(row.get('price') and row.get('h_price') for row in data['rows']), 'A/H quote legs missing')
            for row in data['rows']:
                premium = row['metrics']['ah_premium_pct']
                if premium is not None:
                    require(row['as_of'] == row['price_as_of'] == row['h_price_as_of'] == row['fx_as_of'],
                            'A/H comparison used incompatible source dates')
                    expected = (row['price'] / (row['h_price'] * row['fx_hkd_cny']) - 1) * 100
                    require(abs(expected - premium) < 1e-8, 'A/H FX direction/formula is invalid')
        elif category == 'qdii':
            require(all(row.get('price') and row.get('quote_at') for row in data['rows']), 'QDII quotes/time missing')
            require(all(row.get('eligibility_source_url') and row.get('eligibility_as_of')
                        and row.get('eligibility_status') in {'exchange_listed', 'snapshot_pending_verification'}
                        for row in data['rows']), 'QDII qualification provenance is missing')
        result['markets'][category] = {
            'rows': len(data['rows']), 'attempts': data['attempts'], 'warnings': data['warnings'],
            'computed_comparisons': sum(row['metrics']['ah_premium_pct'] is not None for row in data['rows']),
            'first': {key: value for key, value in data['rows'][0].items()
                      if key not in {'metrics', 'warnings'}},
        }
        print(f'Installed dataset {category}: {len(data["rows"])} rows', flush=True)
    fund = '510300.SH'
    profile = json_request(base, f'/api/ext/funds/{fund}/profile', timeout=180)
    nav = json_request(base, f'/api/ext/funds/{fund}/nav?range=year', timeout=180)
    holdings = json_request(base, f'/api/ext/funds/{fund}/holdings', timeout=180)
    require(bool(profile.get('profile', {}).get('fund_name')), 'Fund profile is empty')
    require(len(nav.get('items', [])) > 100, 'Fund NAV missing or silently truncated to one page')
    require(all(point.get('adj_nav') is None for point in nav['items']), 'Cumulative NAV mislabeled as adjusted NAV')
    require(bool(holdings.get('items')), 'Published fund holdings missing')
    require(all(response.get('provider') == 'eastmoney_public' for response in (profile, nav, holdings)),
            'Fund provenance is incorrect')
    result['fund'] = {'ticker': fund, 'nav_rows': len(nav['items']),
                      'last_nav_date': nav['items'][-1]['date'], 'holdings': len(holdings['items']),
                      'report_date': holdings['items'][0]['report_date'], 'source': profile['provider']}
    from research_enrichment_smoke import check_enrichment
    result['fund_bond_enrichment'] = check_enrichment(base, json_request, require)
    return result


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
                        live = check_live_api(base)
                        return {"health": True, "funds_api": True, "convertibles_api": True,
                                "visible_window": True, "webview2": True, "verified_live_fallback": live}
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
