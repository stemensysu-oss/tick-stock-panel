"""Fund-specific fallback; cumulative NAV is never labelled adjusted NAV."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from html.parser import HTMLParser

from app.custom.funds.models import (
    FundNavPoint,
    FundNavResponse,
    FundProfile,
    FundProfileResponse,
)
from app.custom.funds.provider import FuyaoFundProvider, get_api_key
from app.custom.funds.service import FundDataError
from app.data_providers.research_market import PUBLIC, SH, PublicHTTP, number


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def text(html):
    parser = Text()
    parser.feed(html)
    return ' '.join(''.join(parser.parts).split())


class Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.links = [], [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in {'td', 'th'}:
            self.cell = []
            self.links = []
        elif tag == 'a' and self.cell is not None:
            self.links.append(dict(attrs).get('href', ''))

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append((' '.join(''.join(self.cell).split()), self.links))
            self.cell = None
        elif tag == 'tr' and self.row:
            self.rows.append(self.row)


class EastmoneyFundProvider:
    name = PUBLIC

    def __init__(self, http=None):
        self.http = http or PublicHTTP()
        self.shared_http = http is None

    @staticmethod
    def meta(ticker):
        return dict(ticker=ticker, provider=PUBLIC,
                    timestamp_ms=int(datetime.now(SH).timestamp() * 1000))

    def profile(self, ticker):
        if self.shared_http:
            return _profile(ticker, int(time.monotonic() // 300)).model_copy(deep=True)
        return self._profile(ticker)

    def _profile(self, ticker):
        html = self.http.get(f'https://fundf10.eastmoney.com/jbgk_{ticker[:6]}.html').text
        table = re.search(r'<table[^>]*class=["\']info w790["\'][^>]*>(.*?)</table>', html, re.S)
        if not table:
            raise FundDataError(502, '公开基金资料页面格式已变化，未采用本次结果')
        fields = {text(k): text(v) for k, v in re.findall(
            r'<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)(?=</td>|<th|</tr>)', table[1], re.S)}
        if not fields.get('基金代码', '').startswith(ticker[:6]) or not fields.get('基金全称'):
            raise FundDataError(404, '公开资料未找到所请求基金')
        established = re.search(r'(\d{4})年(\d{2})月(\d{2})日', fields.get('成立日期/规模', ''))
        return FundProfileResponse(**self.meta(ticker), profile=FundProfile(
            fund_name=fields['基金全称'], mgmt_name=fields.get('基金管理人'),
            manager_name=fields.get('基金经理人'),
            established_date='-'.join(established.groups()) if established else None,
            fund_type=fields.get('基金类型'),
            series_kind=('money' if '货币' in fields.get('基金类型', '') else
                         'nav' if fields.get('基金类型') else 'unknown'),
        ), warnings=['公开资料补充源；资料更新日期未提供。净值另按实际公布日期展示。'])

    def nav(self, ticker, nav_range):
        profile = self.profile(ticker).profile
        kind = profile.series_kind if profile else 'unknown'
        if kind == 'unknown':
            raise FundDataError(502, '无法核对基金类型，未将未分类数据当作普通净值')
        days = {'week': 7, 'month': 31, 'tmonth': 93, 'hyear': 184, 'year': 366,
                'twoyear': 732, 'tyear': 1098, 'fyear': 1830}[nav_range]
        cutoff = (datetime.now(SH).date() - timedelta(days=days)).isoformat()
        items, seen = [], set()
        def fetch(page):
            return self.http.get('https://api.fund.eastmoney.com/f10/lsjz', {
                'fundCode': ticker[:6], 'pageIndex': page, 'pageSize': 20,
                'startDate': cutoff, 'endDate': datetime.now(SH).date().isoformat(),
            }).json()
        first = fetch(1)
        total = int(first.get('TotalCount') or 0)
        if total > 2000:
            raise FundDataError(502, '公开净值区间超出 2000 条限制，请缩小区间')
        # The server clamps PageSize to 20 even if 100/500 is requested.
        # Use its actual pagination, otherwise a year silently becomes 20 days.
        with ThreadPoolExecutor(max_workers=4) as pool:
            payloads = [first, *pool.map(fetch, range(2, (total + 19) // 20 + 1))]
        for payload in payloads:
            rows = (payload.get('Data') or {}).get('LSJZList')
            if payload.get('ErrCode') != 0 or not isinstance(rows, list):
                raise FundDataError(502, '公开净值源返回异常')
            for row in rows:
                if kind == 'money' and str(row.get('NAVTYPE')) != '1':
                    raise FundDataError(502, '货币基金收益字段类型无法核对，本次未采用')
                day = row.get('FSRQ')
                date.fromisoformat(day)
                if day in seen or day < cutoff or day > datetime.now(SH).date().isoformat():
                    continue
                seen.add(day)
                items.append(FundNavPoint(date=day,
                    income_per_10000=number(row.get('DWJZ')) if kind == 'money' else None,
                    seven_day_yield_pct=number(row.get('LJJZ')) if kind == 'money' else None,
                    unit_nav=number(row.get('DWJZ'), positive=True) if kind == 'nav' else None,
                    cumulative_nav=number(row.get('LJJZ'), positive=True) if kind == 'nav' else None))
        if len(seen) != total:
            raise FundDataError(502, '公开净值分页不完整，未采用截断结果')
        return FundNavResponse(**self.meta(ticker), range=nav_range, series_kind=kind,
                               items=sorted(items, key=lambda item: item.date),
                               warnings=[('货币基金：万份收益（元/万份）与七日年化（%）为公布值，不是单位/累计/复权净值，也不是收益承诺。'
                                    if kind == 'money' else '单位净值、累计净值分别展示；累计净值不冒充复权净值，复权口径保持未知。')])

    def trading(self, ticker):
        from app.custom.funds.disclosures import PublicFundDisclosures
        return PublicFundDisclosures(self).trading(ticker)

    def dividends(self, ticker):
        from app.custom.funds.disclosures import PublicFundDisclosures
        return PublicFundDisclosures(self).dividends(ticker)

    def holdings_history(self, ticker, asset_type, report_date=None):
        from app.custom.funds.disclosures import PublicFundDisclosures
        return PublicFundDisclosures(self).holdings(ticker, asset_type, report_date)

    def holdings(self, ticker):
        # Keep the legacy route on the same parser as the filtered route;
        # otherwise its old six-digit-only path silently discards HK positions.
        return self.holdings_history(ticker, 'stock')


class FallbackFundProvider:
    """The integrated TickFlow contract has no fund profile/NAV/holdings dataset.

    Fuyao is attempted first for each supported dataset. Only an exception or
    empty usable dataset permits public fallback; primary success is untouched.
    """
    def __init__(self, primary=None, fallback=None, key_getter=None):
        self.key_getter = key_getter or get_api_key
        self.primary = primary
        self.fallback = fallback or EastmoneyFundProvider()

    def _call(self, operation, *args):
        attempts = [{'provider': 'tickflow', 'status': 'unsupported'}]
        key = self.key_getter()
        if key or self.primary is not None:
            try:
                result = getattr(self.primary or FuyaoFundProvider(key), operation)(*args)
                usable = (result.profile is not None and bool(result.profile.fund_name) if operation == 'profile'
                          else any(p.unit_nav is not None or p.adj_nav is not None or p.income_per_10000 is not None for p in result.items) if operation == 'nav'
                          else bool(result.subscription_status or result.redemption_status) if operation == 'trading'
                          else bool(result.items))
                attempts.append({'provider': 'fuyao', 'status': 'success' if usable else 'empty'})
                if usable:
                    return result.model_copy(update={'attempts': attempts})
            except NotImplementedError:
                attempts.append({'provider': 'fuyao', 'status': 'unsupported'})
            except Exception:  # noqa: BLE001 -- redact supplier exceptions that can contain keys
                attempts.append({'provider': 'fuyao', 'status': 'failed'})
        else:
            attempts.append({'provider': 'fuyao', 'status': 'unconfigured'})
        try:
            result = getattr(self.fallback, operation)(*args)
            return result.model_copy(update={'attempts': [*attempts, {'provider': PUBLIC, 'status': 'success'}]})
        except Exception:  # noqa: BLE001 -- only a fixed safe message crosses the route boundary
            raise FundDataError(502, '主数据源与公开补充源均未返回可用基金数据，请稍后重试或检查基金代码及主 API 权限') from None

    def profile(self, ticker):
        result = self._call('profile', ticker)
        if result.profile and result.profile.series_kind == 'unknown' and self.primary is None:
            try:
                metadata = self.fallback.profile(ticker)
                if metadata.profile:
                    info = metadata.profile
                    result = result.model_copy(update={'profile': result.profile.model_copy(update={
                        'fund_type': info.fund_type, 'series_kind': info.series_kind,
                        'unit_nav': None if info.series_kind == 'money' else result.profile.unit_nav}),
                        'warnings': [*result.warnings, '基金类型由东方财富公开资料补充核对。']})
            except Exception:  # noqa: BLE001
                result = result.model_copy(update={'profile': result.profile.model_copy(update={'unit_nav': None}),
                    'warnings': [*result.warnings, '基金类型无法核对，资料中的单位净值暂不采用。']})
        return result

    def nav(self, ticker, nav_range):
        if self.primary is None:
            # Neither original API documents the money-income series. Classify
            # using public fund metadata before interpreting overloaded fields.
            try:
                info = self.fallback.profile(ticker).profile
            except Exception:  # noqa: BLE001 -- safe classification failure
                raise FundDataError(502, '无法核对基金类型，本次净值/收益未采用') from None
            if not info or info.series_kind == 'unknown':
                raise FundDataError(502, '无法核对基金类型，本次净值/收益未采用')
            if info.series_kind == 'money':
                try:
                    result = self.fallback.nav(ticker, nav_range)
                except FundDataError:
                    raise
                except Exception:  # noqa: BLE001 -- money series bypasses the generic source chain
                    raise FundDataError(502, '公开货币基金收益源暂不可用，本次结果未采用，请稍后重试') from None
                return result.model_copy(update={'attempts': [
                    {'provider': 'tickflow', 'status': 'unsupported'},
                    {'provider': 'fuyao', 'status': 'unsupported'},
                    {'provider': PUBLIC, 'status': 'success'}]})
        return self._call('nav', ticker, nav_range)

    def holdings(self, ticker):
        return self._call('holdings', ticker)

    def holdings_history(self, ticker, asset_type, report_date=None):
        return self._call('holdings_history', ticker, asset_type, report_date)

    def dividends(self, ticker):
        return self._call('dividends', ticker)

    def trading(self, ticker):
        return self._call('trading', ticker)


@lru_cache(maxsize=128)
def _profile(ticker, bucket):
    # Time-bucketed, bounded, public-only cache. Failed requests are not cached.
    return EastmoneyFundProvider(PublicHTTP())._profile(ticker)
