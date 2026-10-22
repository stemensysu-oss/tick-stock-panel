"""Explicit A/H company directory, independent quote legs and dated CNY/HKD FX.

The directory contains codes only. Quotes always pass through the existing
TickFlow -> Fuyao -> public chain; no quote is inferred from a directory row.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.data_providers.research_market import (
    DISCLOSURE,
    LABELS,
    SH,
    PublicHTTP,
    ResearchMarketService,
    ResearchSourceError,
    number,
    quote_time,
)
from app.services.multi_asset_models import AssetInput

PAIR_URL = 'https://www.aastocks.com/en/stocks/market/ah.aspx?filter=1&sort=1'
PAIR_SNAPSHOT_DATE = '2026-10-22'
# Captured from explicit A and H link titles in the public comparison table.
# No prices, returns, names, currencies or exchange rates are embedded.
PAIR_SNAPSHOT = (
    ('601038.SH', '00038.HK'),
    ('601107.SH', '00107.HK'),
    ('600600.SH', '00168.HK'),
    ('600377.SH', '00177.HK'),
    ('600860.SH', '00187.HK'),
    ('600685.SH', '00317.HK'),
    ('600808.SH', '00323.HK'),
    ('600688.SH', '00338.HK'),
    ('600362.SH', '00358.HK'),
    ('600028.SH', '00386.HK'),
    ('601390.SH', '00390.HK'),
    ('603501.SH', '00501.HK'),
    ('601333.SH', '00525.HK'),
    ('688337.SH', '00537.HK'),
    ('600548.SH', '00548.HK'),
    ('600775.SH', '00553.HK'),
    ('601717.SH', '00564.HK'),
    ('601588.SH', '00588.HK'),
    ('601598.SH', '00598.HK'),
    ('600115.SH', '00670.HK'),
    ('600699.SH', '00699.HK'),
    ('601728.SH', '00728.HK'),
    ('601111.SH', '00753.HK'),
    ('601811.SH', '00811.HK'),
    ('601857.SH', '00857.HK'),
    ('600332.SH', '00874.HK'),
    ('600938.SH', '00883.HK'),
    ('600011.SH', '00902.HK'),
    ('600585.SH', '00914.HK'),
    ('601939.SH', '00939.HK'),
    ('600941.SH', '00941.HK'),
    ('600956.SH', '00956.HK'),
    ('688981.SH', '00981.HK'),
    ('601991.SH', '00991.HK'),
    ('600012.SH', '00995.HK'),
    ('601998.SH', '00998.HK'),
    ('600871.SH', '01033.HK'),
    ('601005.SH', '01053.HK'),
    ('600029.SH', '01055.HK'),
    ('600874.SH', '01065.HK'),
    ('600027.SH', '01071.HK'),
    ('600875.SH', '01072.HK'),
    ('601088.SH', '01088.HK'),
    ('600876.SH', '01108.HK'),
    ('600026.SH', '01138.HK'),
    ('600188.SH', '01171.HK'),
    ('601186.SH', '01186.HK'),
    ('600276.SH', '01276.HK'),
    ('601288.SH', '01288.HK'),
    ('688279.SH', '01304.HK'),
    ('601330.SH', '01330.HK'),
    ('601336.SH', '01336.HK'),
    ('601319.SH', '01339.HK'),
    ('688347.SH', '01347.HK'),
    ('688505.SH', '01349.HK'),
    ('601375.SH', '01375.HK'),
    ('688385.SH', '01385.HK'),
    ('601398.SH', '01398.HK'),
    ('601456.SH', '01456.HK'),
    ('601828.SH', '01528.HK'),
    ('601618.SH', '01618.HK'),
    ('600635.SH', '01635.HK'),
    ('601658.SH', '01658.HK'),
    ('601766.SH', '01766.HK'),
    ('600547.SH', '01787.HK'),
    ('601800.SH', '01800.HK'),
    ('688236.SH', '01858.HK'),
    ('688180.SH', '01877.HK'),
    ('601888.SH', '01880.HK'),
    ('601898.SH', '01898.HK'),
    ('601919.SH', '01919.HK'),
    ('601963.SH', '01963.HK'),
    ('600016.SH', '01988.HK'),
    ('601992.SH', '02009.HK'),
    ('601916.SH', '02016.HK'),
    ('601068.SH', '02068.HK'),
    ('600196.SH', '02196.HK'),
    ('605198.SH', '02218.HK'),
    ('601238.SH', '02238.HK'),
    ('688249.SH', '02249.HK'),
    ('688796.SH', '02315.HK'),
    ('601318.SH', '02318.HK'),
    ('601633.SH', '02333.HK'),
    ('603259.SH', '02359.HK'),
    ('688339.SH', '02402.HK'),
    ('603906.SH', '02465.HK'),
    ('688062.SH', '02493.HK'),
    ('601600.SH', '02600.HK'),
    ('601601.SH', '02601.HK'),
    ('601607.SH', '02607.HK'),
    ('601211.SH', '02611.HK'),
    ('601628.SH', '02628.HK'),
    ('688234.SH', '02631.HK'),
    ('688036.SH', '02636.HK'),
    ('603345.SH', '02648.HK'),
    ('688052.SH', '02676.HK'),
    ('603093.SH', '02691.HK'),
    ('601727.SH', '02727.HK'),
    ('601866.SH', '02866.HK'),
    ('601880.SH', '02880.HK'),
    ('601808.SH', '02883.HK'),
    ('601899.SH', '02899.HK'),
    ('603228.SH', '03228.HK'),
    ('603288.SH', '03288.HK'),
    ('603296.SH', '03296.HK'),
    ('601328.SH', '03328.HK'),
    ('601326.SH', '03369.HK'),
    ('600660.SH', '03606.HK'),
    ('601077.SH', '03618.HK'),
    ('688187.SH', '03898.HK'),
    ('601995.SH', '03908.HK'),
    ('600958.SH', '03958.HK'),
    ('600036.SH', '03968.HK'),
    ('688009.SH', '03969.HK'),
    ('603986.SH', '03986.HK'),
    ('601988.SH', '03988.HK'),
    ('603993.SH', '03993.HK'),
    ('601868.SH', '03996.HK'),
    ('600030.SH', '06030.HK'),
    ('600031.SH', '06031.HK'),
    ('601066.SH', '06066.HK'),
    ('600999.SH', '06099.HK'),
    ('603127.SH', '06127.HK'),
    ('688235.SH', '06160.HK'),
    ('603083.SH', '06166.HK'),
    ('601788.SH', '06178.HK'),
    ('688185.SH', '06185.HK'),
    ('601298.SH', '06198.HK'),
    ('600801.SH', '06655.HK'),
    ('600690.SH', '06690.HK'),
    ('600988.SH', '06693.HK'),
    ('688031.SH', '06727.HK'),
    ('601678.SH', '06745.HK'),
    ('688008.SH', '06809.HK'),
    ('601818.SH', '06818.HK'),
    ('688366.SH', '06826.HK'),
    ('601865.SH', '06865.HK'),
    ('601869.SH', '06869.HK'),
    ('601881.SH', '06881.HK'),
    ('601688.SH', '06886.HK'),
    ('603650.SH', '09607.HK'),
    ('603341.SH', '09611.HK'),
    ('688630.SH', '09630.HK'),
    ('601127.SH', '09927.HK'),
    ('688428.SH', '09969.HK'),
    ('605499.SH', '09980.HK'),
    ('688331.SH', '09995.HK'),
)
FX_URL = 'https://qt.gtimg.cn/q=whHKDCNY'


@dataclass
class AHBatch:
    rows: list[AssetInput]
    fetched_at: str
    attempts: list[dict]
    warnings: list[str] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)


def parse_pairs(body):
    pairs = {}
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', body, re.I | re.S):
        codes = set(re.findall(r"title=['\"](\d{5}\.HK|\d{6}\.(?:SH|SZ))['\"]", tr))
        a = [c for c in codes if not c.endswith('.HK')]
        h = [c for c in codes if c.endswith('.HK')]
        if len(a) == len(h) == 1:
            if a[0] in pairs and pairs[a[0]] != h[0]:
                raise ResearchSourceError('A/H 目录存在冲突配对')
            pairs[a[0]] = h[0]
    if not 10 <= len(pairs) <= 500 or len(set(pairs.values())) != len(pairs):
        raise ResearchSourceError('A/H 目录为空、超限或重复')
    return sorted(pairs.items())


def public_pairs(http):
    try:
        pairs = parse_pairs(http.get(PAIR_URL).text)
        return pairs, [{'provider': 'aastocks_public', 'dataset': 'ah_pairs',
                        'status': 'success', 'rows': len(pairs)}], []
    except (ResearchSourceError, ValueError, TypeError):
        return list(PAIR_SNAPSHOT), [
            {'provider': 'aastocks_public', 'dataset': 'ah_pairs', 'status': 'failed'},
            {'provider': 'aastocks_directory_snapshot', 'dataset': 'ah_pairs',
             'status': 'success', 'rows': len(PAIR_SNAPSHOT)}], [
                 f'A/H 在线配对目录读取失败，使用 {PAIR_SNAPSHOT_DATE} 明确代码配对快照；可能缺少新上市或变更。目录不含价格。']


def public_fx(http):
    """Tencent whHKDCNY reports CNY per HKD and its own full source timestamp."""
    body = http.get(FX_URL).content.decode('gb18030')
    match = re.search(r'v_whHKDCNY="([^"\r\n]*)";', body)
    if not match:
        raise ResearchSourceError('汇率补充源未返回 HKDCNY')
    fields = match[1].split('~')
    if len(fields) < 22 or fields[2] != 'HKDCNY' or not re.fullmatch(r'\d{14}', fields[5]):
        raise ResearchSourceError('汇率补充源币对或时间异常')
    dt = datetime.strptime(fields[5], '%Y%m%d%H%M%S').replace(tzinfo=SH)
    when = quote_time(dt.timestamp())
    rate = number(fields[3], positive=True)
    if rate is None or not 0.1 <= rate <= 2 or fields[21] != when[:10]:
        raise ResearchSourceError('汇率补充源方向、数值或日期异常')
    return {'value': rate, 'quote_at': when, 'source': 'tencent_public',
            'source_name': '腾讯公开 HKDCNY（人民币/港元）', 'source_url': FX_URL}


class AHService:
    def __init__(self, market=None, http=None):
        self.market = market or ResearchMarketService()
        self.http = http or PublicHTTP()

    def fetch(self):
        # Neither documented primary contract provides issuer pair directories
        # or HKDCNY FX. Record those capability gaps rather than invent endpoints.
        attempts = [{'provider': p, 'dataset': dataset, 'status': 'unsupported'}
                    for dataset in ('ah_pairs', 'fx_hkd_cny') for p in ('tickflow', 'fuyao')]
        pairs, directory_attempts, warnings = public_pairs(self.http)
        attempts.extend(directory_attempts)
        fx = None
        try:
            fx = public_fx(self.http)
            attempts.append({'provider': 'tencent_public', 'dataset': 'fx_hkd_cny', 'status': 'success', 'rows': 1})
        except (ResearchSourceError, ValueError):
            attempts.append({'provider': 'tencent_public', 'dataset': 'fx_hkd_cny', 'status': 'failed'})
            warnings.append('独立 HKDCNY 汇率未取得，保留两地报价，A/H 溢价不可计算。')
        quotes = self.market.fetch('quotes', [s for pair in pairs for s in pair])
        attempts.extend({**a, 'dataset': 'ah_quotes'} for a in quotes.attempts)
        warnings.extend(quotes.warnings)
        fetched = datetime.now(SH)
        by_code = {r.symbol: r for r in quotes.rows}
        rows, metadata, unsynced, missing = [], [], 0, 0
        for a_code, h_code in pairs:
            a, h = by_code.get(a_code), by_code.get(h_code)
            # Explicit HKD is required, including when primary providers succeed.
            if h and h.extra.get('currency') != 'HKD':
                h = None
            if not a and not h:
                missing += 1
                continue
            days = [r.quote_at[:10] for r in (a, h) if r]
            if fx:
                days.append(fx['quote_at'][:10])
            aligned = len(days) == 3 and len(set(days)) == 1
            fresh = all(datetime.fromisoformat(d).date() >= (fetched - timedelta(days=7)).date() for d in days)
            if not aligned or not fresh:
                unsynced += 1
            # Strict presentation contract suppresses the metric for unequal dates.
            as_of = days[0] if aligned and fresh else fetched.date().isoformat()
            notes = ('明确 A/H 代码配对；A 股人民币，H 股港元；A/H 不代表可互换或无风险套利。'
                     '公开港股报价通常延迟约 15 分钟，以两地和汇率独立时点为准。')
            if not aligned or not fresh:
                notes += '两地价格/汇率日期不一致、缺失或超过 7 天，A/H 溢价不可计算。'
            sources = ' / '.join(dict.fromkeys(LABELS.get(r.source, r.source) for r in (a, h) if r))
            rows.append(AssetInput(
                code=a_code, name=a.name if a else h.name, currency='CNY',
                source_name=sources, source_url=PAIR_URL, as_of=as_of,
                price=a.price if a else None, price_as_of=a.quote_at[:10] if a else None,
                h_code=h_code, h_price=h.price if h else None, h_currency='HKD' if h else None,
                h_price_as_of=h.quote_at[:10] if h else None,
                fx_hkd_cny=fx['value'] if fx else None, fx_as_of=fx['quote_at'][:10] if fx else None,
                notes=notes))
            metadata.append({
                'quote_at': a.quote_at if a else None, 'h_quote_at': h.quote_at if h else None,
                'fx_quote_at': fx['quote_at'] if fx else None,
                'fx_source_name': fx['source_name'] if fx else None,
                'fx_source_url': fx['source_url'] if fx else None,
                'pair_source_url': PAIR_URL, 'pair_directory_snapshot_date':
                    PAIR_SNAPSHOT_DATE if any('snapshot' in x['provider'] for x in directory_attempts) else None,
                'source_id': a.source if a else h.source,
                'a_source_id': a.source if a else None, 'h_source_id': h.source if h else None,
                'h_currency_source': h.extra.get('currency_source', h.source) if h else None,
                'comparison_status': 'available' if aligned and fresh else 'unavailable',
            })
        if not rows:
            raise ResearchSourceError('A/H 配对未取得有效两地行情，请稍后重试')
        if unsynced:
            warnings.append(f'{unsynced} 对的价格/汇率日期不一致、缺失或超过 7 天；溢价保持不可计算。')
        if missing:
            warnings.append(f'{missing} 对未取得任一有效报价，未伪造价格。')
        warnings.extend([DISCLOSURE, 'A/H 采用 (A 股价 / (H 股价 × CNY/HKD 汇率) - 1) × 100%；汇率是参考报价，不是可成交结汇价。'])
        return AHBatch(rows, fetched.isoformat(timespec='seconds'), attempts, list(dict.fromkeys(warnings)), metadata)


_CACHE = None
_LOCK = threading.Lock()


def ah_batch(*, force=False):
    global _CACHE
    with _LOCK:
        cached = _CACHE
    if cached and not force and time.monotonic() - cached[0] < 60:
        return cached[1]
    result = AHService().fetch()
    with _LOCK:
        _CACHE = (time.monotonic(), result)
    return result
