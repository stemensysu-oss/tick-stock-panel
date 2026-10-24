"""One dated HK dataset shared by chart, levels and the AI prompt."""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from copy import deepcopy
from datetime import datetime

import anyio
import polars as pl

from app.data_providers.research_hk_daily import fetch_daily
from app.data_providers.research_market import LABELS, SH, ResearchSourceError
from app.indicators.levels import compute_levels, summarize_levels
from app.indicators.pipeline import compute_indicators
from app.services.watchlist_hk import is_hk, quote_snapshot

_CACHE = {}
_LOCK = threading.Lock()
INDICATORS = {'ma5', 'ma10', 'ma20', 'ma60', 'macd_dif', 'macd_dea', 'macd_hist',
              'kdj_k', 'kdj_d', 'kdj_j', 'rsi_14', 'boll_upper', 'boll_lower', 'atr_14'}


def snapshot(symbol, force=False):
    if not is_hk(symbol):
        raise ValueError('请输入完整的五位港股代码，如00700.HK')
    from app import secrets_store
    identity = hashlib.sha256(((secrets_store.get_tickflow_key() or '') + '\0' +
        (secrets_store.load().get('tickflow_base_url') or '')).encode()).hexdigest()
    key = (symbol, identity)
    with _LOCK:
        saved = _CACHE.get(key)
    if saved and not force and time.monotonic() - saved[0] < 300:
        return deepcopy(saved[1])
    # Currency is verified explicitly by the quote chain, not inferred from .HK.
    quotes = quote_snapshot([symbol], force=force)
    quote = next((r for r in quotes['rows'] if r['symbol'] == symbol and r['currency'] == 'HKD'), None)
    if not quote:
        raise ResearchSourceError('港股币种尚未确认，暂不混合历史价格进行分析')
    daily = fetch_daily(symbol)
    frame = pl.DataFrame(daily['rows']).with_columns(pl.col('date').str.to_date())
    frame = compute_indicators(frame, needed=INDICATORS).tail(250)
    levels = compute_levels(frame)
    # No verified historical turnover: do not label a cumulative volume proxy as chips.
    levels['sr'] = []
    from app.services.stock_analysis_series import _build_series
    def clean(v):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return v
    rows = [{k: clean(v) for k, v in r.items() if not k.startswith('_')}
            for r in frame.to_dicts()]
    value = dict(symbol=symbol, name=quote['name'], asset_type='hk', currency='HKD',
        price_basis='unadjusted', volume_unit='source_native', rows=rows,
        levels=levels, series=_build_series(frame), dates=[r['date'] for r in rows],
        close=rows[-1]['close'], as_of=rows[-1]['date'], quote=quote,
        source=daily['source'], source_name=LABELS.get(daily['source'], daily['source']),
        fetched_at=datetime.now(SH).isoformat(timespec='seconds'),
        attempts=daily['attempts'], warnings=[
            '日K为不复权港元价格，仅使用今天之前的已完成日期；分红、拆合股可能造成价格跳空。',
            '成交量保留来源原单位，未用于金额或换手率换算；筹码压力支撑因缺历史换手率未启用。',
            '关键价位基于所列历史样本计算，不是实时成交价或保证可成交的价格。',
            '港股财务报表与直接新闻尚未接入；AI只分析已提供的技术数据，不补造其他维度。'])
    with _LOCK:
        if len(_CACHE) >= 32:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), deepcopy(value))
    return value


def ai_messages(data, focus=''):
    from app.services.ai_provider import build_focus_instruction
    system = ('你是客观的港股技术分析师。只使用提供的数据，输出中文Markdown。'
        '价格均为HKD不复权历史价格，不得套用A股涨跌停、连板、T+1、人民币或A股财报规则。'
        '依次说明样本日期与来源、技术趋势及指标、关键价位、数据缺失与风险。'
        '每条数值结论需对应输入；财务、基本面与直接新闻均缺失，明确无法评估，不能凭常识编造。'
        '没有历史换手率，不推断筹码持仓；成交量原单位不作金额换算。'
        '分红拆合股可导致不复权跳空，不得当作真实收益或确定突破。'
        '不输出买卖、仓位、交易指令，不将历史最后收盘称为当前实时价格。')
    if data.get('asset_type') in {'us','jp'}:
        system = system.replace('港股',data['market_label']).replace('HKD',data['currency'])
        system += '不得套用香港或内地规则，交易日期按输入市场当地日期。'
        if data.get('price_basis') == 'source_unspecified':
            system = system.replace('不复权历史价格', '来源未说明复权口径的历史价格')
            system += '不得断言复权方式，也不能把样本涨幅解释为包含分红的实际收益。'
    payload = {k: data[k] for k in ('symbol', 'name', 'currency', 'price_basis', 'volume_unit',
        'as_of', 'source_name', 'fetched_at', 'warnings', 'levels')}
    payload['daily'] = data['rows'][-90:]
    return [{'role': 'system', 'content': system}, {'role': 'user',
        'content': json.dumps(payload, ensure_ascii=False) + '\n' +
                   build_focus_instruction(focus, report_name='港股技术分析报告')}]


async def analyze_stream(symbol, focus='', *, loader=None):
    try:
        data = await anyio.to_thread.run_sync(loader or snapshot, symbol)
        yield json.dumps(dict(type='meta', symbol=symbol, close=data['close'], levels=data['levels'],
            summary=f"{data.get('market_label', '港股')} {data['currency']} · {'不复权' if data['price_basis'] == 'unadjusted' else '来源未说明复权口径'} · {data['as_of']} · {data['source_name']}；" +
                    summarize_levels(data['levels'], data['close']).replace('当前价 ', '历史收盘 ', 1)), ensure_ascii=False)
        from app.services.ai_provider import stream_ai_text
        content = False
        async for delta in stream_ai_text(ai_messages(data, focus), temperature=0.3,
                                          max_tokens=None, prefer_final_answer=True):
            if delta:
                content = True
                yield json.dumps(dict(type='delta', content=delta), ensure_ascii=False)
        if not content:
            raise ValueError('empty model response')
        yield json.dumps(dict(type='done'))
    except Exception:  # noqa: BLE001 -- do not return provider keys or upstream raw errors
        yield json.dumps(dict(type='error', message='AI分析未完成：请检查日K数据及设置中的AI服务配置或权限，原有报告保留。'), ensure_ascii=False)
