"""HK daily bars: raw prices, dated sessions, no mainland storage or rules."""
from __future__ import annotations

from datetime import date, datetime

from app.data_providers.research_market import SH, PublicHTTP, ResearchSourceError, number


def validate_bars(rows, symbol):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ResearchSourceError('港股日K为空或条数异常')
    result, seen = [], set()
    today = datetime.now(SH).date()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ResearchSourceError('港股日K格式异常')
        day = date.fromisoformat(raw['date'])
        if day in seen or day > today:
            raise ResearchSourceError('港股日K存在重复或未来日期')
        seen.add(day)
        values = {key: number(raw.get(key), positive=True) for key in ('open', 'high', 'low', 'close')}
        if (any(v is None for v in values.values()) or values['low'] > min(values['open'], values['close'])
                or values['high'] < max(values['open'], values['close']) or values['high'] < values['low']):
            raise ResearchSourceError('港股日K价格关系异常')
        volume = number(raw.get('volume'))
        if volume is not None and volume < 0:
            raise ResearchSourceError('港股成交量异常')
        # Today's bar can still change. Technical analysis uses completed prior dates.
        if day < today:
            result.append(dict(symbol=symbol, date=day.isoformat(), **values, volume=volume))
    result.sort(key=lambda row: row['date'])
    if len(result) < 30:
        raise ResearchSourceError('港股已完成日K不足30条，暂不生成关键价位与AI分析')
    return result


class TickflowHkDaily:
    name = 'tickflow'

    def fetch(self, symbol, count):
        from tickflow import TickFlow

        from app import secrets_store
        key = secrets_store.get_tickflow_key()
        if not key:
            raise PermissionError
        client = TickFlow(api_key=key, base_url=secrets_store.load().get('tickflow_base_url') or None,
                          timeout=12, max_retries=0)
        try:
            data = client.klines.get(symbol, period='1d', count=count, adjust='none')
        finally:
            client.close()
        fields = ('timestamp', 'open', 'high', 'low', 'close', 'volume')
        if not isinstance(data, dict) or any(not isinstance(data.get(k), list) for k in fields):
            raise ResearchSourceError('主API港股日K格式异常')
        if len({len(data[k]) for k in fields}) != 1:
            raise ResearchSourceError('主API港股日K列长度不一致')
        rows = []
        for i, stamp in enumerate(data['timestamp']):
            stamp = number(stamp, positive=True)
            day = datetime.fromtimestamp(stamp / 1000, SH).date().isoformat()
            rows.append(dict(date=day, **{k: data[k][i] for k in fields[1:]}))
        return validate_bars(rows, symbol)


class FuyaoHkDaily:
    name = 'fuyao'

    def fetch(self, symbol, count):
        # Published historical price contract is A-share; HK contract is IPO.
        # Never submit HK codes to the mainland endpoint or guess an API path.
        raise NotImplementedError


class TencentHkDaily:
    name = 'tencent_public'

    def fetch(self, symbol, count):
        code = 'hk' + symbol[:5]
        data = PublicHTTP().get('https://web.ifzq.gtimg.cn/appstock/app/kline/kline',
                                {'param': f'{code},day,,,{count}'}).json()
        if data.get('code') != 0:
            raise ResearchSourceError('公开港股日K响应异常')
        raw = (data.get('data') or {}).get(code, {}).get('day')
        if not isinstance(raw, list):
            raise ResearchSourceError('公开港股日K为空')
        rows = []
        for row in raw:
            if not isinstance(row, list) or len(row) < 6:
                raise ResearchSourceError('公开港股日K行格式异常')
            rows.append(dict(zip(('date', 'open', 'close', 'high', 'low', 'volume'), row[:6], strict=True)))
        return validate_bars(rows, symbol)


def fetch_daily(symbol, count=320, providers=None):
    attempts = []
    for provider in providers or [TickflowHkDaily(), FuyaoHkDaily(), TencentHkDaily()]:
        try:
            rows = provider.fetch(symbol, count)
            if not rows:
                raise ResearchSourceError('日K为空')
            attempts.append(dict(provider=provider.name, dataset='hk_daily', status='success', rows=len(rows)))
            return dict(rows=rows, source=provider.name, attempts=attempts)
        except PermissionError:
            status = 'unconfigured'
        except NotImplementedError:
            status = 'unsupported'
        except Exception:  # noqa: BLE001 -- supplier exceptions may contain credentials
            status = 'failed'
        attempts.append(dict(provider=provider.name, dataset='hk_daily', status=status))
    raise ResearchSourceError('主API及公开补充源均未返回有效港股日K；原数据保留，请稍后重试')
