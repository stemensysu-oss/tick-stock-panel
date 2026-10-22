"""Exchange-qualified cross-border T+0 research candidates, not inferred names.

The official SSE directory explicitly filters SWING_TRADE=是 and publishes fund
classification. QDII and Stock Connect funds both occur here: do not claim every
cross-border fund is legally a QDII, or that qualification implies tradability.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.data_providers.research_market import (
    LABELS,
    SH,
    PublicHTTP,
    ResearchMarketService,
    ResearchSourceError,
)
from app.services.multi_asset_models import AssetInput

DIRECTORY_URL = 'https://etf.sse.com.cn/fundlist/'
QUERY_URL = 'https://query.sse.com.cn/commonQuery.do'
QUERY = {'sqlId': 'COMMON_JJZWZ_JJLB_L', 'isPagination': 'false',
         'type': 'inParams', 'CATEGORY': 'F000', 'SWING_TRADE': '是'}
CLASSES = {'F131': '跨境 ETF', 'F214': '跨境 LOF'}
_CACHE, _LOCK = {}, threading.Lock()


@dataclass
class QdiiBatch:
    rows: list[AssetInput]
    fetched_at: str
    attempts: list[dict]
    warnings: list[str]
    metadata: list[dict]


def parse_directory(payload):
    values = payload.get('result') if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values or len(values) > 3000:
        raise ResearchSourceError('交易所回转交易目录为空或格式异常')
    output, seen = [], set()
    for raw in values:
        if not isinstance(raw, dict) or raw.get('CATEGORY') not in CLASSES:
            continue
        code = raw.get('FUND_CODE')
        name = raw.get('FUND_EXPANSION_ABBR') or raw.get('FUND_ABBR')
        if (not isinstance(code, str) or not re.fullmatch(r'\d{6}', code)
                or code in seen or not isinstance(name, str) or not 0 < len(name) <= 100
                or any(ord(char) < 32 for char in name)):
            raise ResearchSourceError('交易所跨境回转目录含异常标的')
        seen.add(code)
        output.append({'code': code, 'name': name, 'category': raw['CATEGORY']})
    if not output:
        raise ResearchSourceError('交易所未返回明确分类的跨境回转基金')
    return output


def _directory(http):
    attempts = [{'provider': 'tickflow', 'operation': 't0_eligibility', 'status': 'unsupported'},
                {'provider': 'fuyao', 'operation': 't0_eligibility', 'status': 'unsupported'}]
    try:
        rows = parse_directory(http.get(QUERY_URL, QUERY).json())
        date = datetime.now(SH).date().isoformat()
        status = 'exchange_listed'
        attempts.append({'provider': 'sse_public', 'operation': 't0_eligibility',
                         'status': 'success', 'rows': len(rows)})
    except Exception:  # noqa: BLE001 -- public network/parser failure, no details exposed
        snapshot = json.loads(Path(__file__).with_name('research_qdii_catalog.json').read_text(encoding='utf-8'))
        rows = parse_directory({'result': [
            {'FUND_CODE': row['code'], 'FUND_ABBR': row['name'], 'CATEGORY': row['category']}
            for row in snapshot['rows']]})
        date, status = snapshot['as_of'], 'snapshot_pending_verification'
        attempts.extend([
            {'provider': 'sse_public', 'operation': 't0_eligibility', 'status': 'failed'},
            {'provider': 'sse_dated_catalog', 'operation': 't0_eligibility',
             'status': 'success', 'rows': len(rows)},
        ])
    return rows, date, status, attempts


def qdii_batch(*, force=False, http=None, service=None):
    """Return inputs and aligned provenance; quotes always follow the main router.

    Snapshot fallback carries code/name/qualification date only. No saved prices,
    NAV, IOPV, premium, subscription status or suspension status are invented.
    """
    cacheable = http is None and service is None
    with _LOCK:
        cached = _CACHE.get('qdii')
    if cacheable and not force and cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    directory, as_of, eligibility, attempts = _directory(http or PublicHTTP())
    qualified = {row['code'] + '.SH': row for row in directory}
    quotes = (service or ResearchMarketService()).fetch('quotes', list(qualified))
    rows, metadata = [], []
    for quote in quotes.rows:
        record = qualified.get(quote.symbol)
        if record is None:
            continue
        notes = (f'上交所{CLASSES[record["category"]]}当日回转名单，资格目录日期 {as_of}；'
                 + ('实时目录已返回。' if eligibility == 'exchange_listed'
                    else '当前目录未能核验，使用历史目录候选，交易资格待复核。')
                 + '跨境基金包含 QDII 与港股通产品；仅提供场内报价，净值、IOPV、申赎和停牌状态未知。')
        rows.append(AssetInput(
            code=quote.symbol, name=quote.name or record['name'], currency='CNY',
            source_name=LABELS.get(quote.source, quote.source),
            source_url=(f'https://qt.gtimg.cn/q=sh{record["code"]}'
                        if quote.source == 'tencent_public'
                        else f'https://quote.eastmoney.com/sh{record["code"]}.html'
                        if quote.source == 'eastmoney_public'
                        else 'https://docs.tickflow.org/zh-Hans'),
            as_of=quote.quote_at[:10], price=quote.price, price_as_of=quote.quote_at[:10], notes=notes))
        metadata.append({'source_id': quote.source, 'quote_at': quote.quote_at,
                         'eligibility_source_url': DIRECTORY_URL, 'eligibility_as_of': as_of,
                         'eligibility_status': eligibility,
                         'eligibility_label': ('交易所回转名单' if eligibility == 'exchange_listed'
                                               else '历史目录候选 · 资格待复核'),
                         'fund_classification': CLASSES[record['category']]})
    if not rows:
        raise ResearchSourceError('已确认的跨境回转候选未获取到有效报价，未使用演示数据')
    warnings = list(quotes.warnings)
    warnings.append('仅覆盖上交所明确列入当日回转名单的跨境 ETF / LOF，非全部沪深 QDII。跨境不等于 QDII；回转资格不代表当前可申赎或未停牌，净值和 IOPV 未接入。')
    if eligibility != 'exchange_listed':
        warnings.append(f'当前交易所资格目录不可用，使用 {as_of} 的代码目录候选；交易资格待复核。行情仍须本次网络取数成功，不使用历史目录中的价格。')
    result = QdiiBatch(rows, quotes.fetched_at, attempts + quotes.attempts, warnings, metadata)
    if cacheable:
        with _LOCK:
            _CACHE['qdii'] = time.monotonic(), result
    return result
