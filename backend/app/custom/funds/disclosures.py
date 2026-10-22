"""Bounded public fund disclosures. HTML/JavaScript are parsed as data, never run."""
from __future__ import annotations

import json
import re
from datetime import date

from app.custom.funds.models import (
    FundDividend,
    FundDividendsResponse,
    FundHolding,
    FundHoldingsResponse,
    FundLimit,
    FundTradingResponse,
)
from app.custom.funds.service import FundDataError
from app.data_providers.research_market import number


def day(value):
    value = value.strip()
    if value in {'', '---', '--', '-', '暂无'}:
        return None
    return date.fromisoformat(value).isoformat()


def limit(value, unit):
    result = FundLimit(unit=unit, source_text=value)
    if value == '无限额':
        return result.model_copy(update={'status': 'unlimited'})
    match = re.fullmatch(r'([\d,]+(?:\.\d+)?)\s*' + ('元' if unit == 'CNY' else '份'), value or '')
    if match:
        amount = number(match[1].replace(',', ''))
        if amount is not None and amount >= 0:
            return result.model_copy(update={'status': 'finite', 'value': amount})
    return result


class PublicFundDisclosures:
    def __init__(self, parent):
        self.parent = parent

    def _page(self, kind, ticker):
        url = f'https://fundf10.eastmoney.com/{kind}_{ticker[:6]}.html'
        html = self.parent.http.get(url).text
        # Verify the page identity before accepting a redirected/generic result.
        title = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
        if not title or ticker[:6] not in title[1]:
            raise FundDataError(502, '公开资料代码不匹配或页面格式已变化')
        return url, html

    def trading(self, ticker):
        from app.custom.funds.fallback import Table

        url, html = self._page('jjfl', ticker)
        parser = Table()
        parser.feed(html)
        fields = {}
        for row in parser.rows:
            for i in range(0, len(row) - 1, 2):
                fields[row[i][0]] = row[i + 1][0]
        if not fields.get('申购状态') or not fields.get('赎回状态'):
            raise FundDataError(502, '公开申赎规则页面格式已变化')
        return FundTradingResponse(**self.parent.meta(ticker), source_url=url,
            subscription_status=fields['申购状态'], redemption_status=fields['赎回状态'],
            minimum_purchase=limit(fields.get('申购起点'), 'CNY'),
            daily_purchase_limit=limit(fields.get('日累计申购限额'), 'CNY'),
            minimum_redemption=limit(fields.get('最小赎回份额'), 'units'),
            minimum_remaining=limit(fields.get('部分赎回最低保留份额'), 'units'),
            warnings=['天天基金销售渠道披露的场外申赎规则，非交易所二级市场交易/ETF一级申赎额度；生效日期未提供，以管理人最新公告及实际交易渠道为准。'])

    def dividends(self, ticker):
        from app.custom.funds.fallback import Table

        _url, html = self._page('fhsp', ticker)
        items = []
        found = False
        for table in re.findall(r'<table\b.*?</table>', html, re.S):
            parser = Table()
            parser.feed(table)
            if not parser.rows:
                continue
            headers = [c[0] for c in parser.rows[0]]
            required = ['权益登记日', '除息日', '每10份分红', '分红发放日']
            if not all(h in headers for h in required):
                continue
            found = True
            for row in parser.rows[1:]:
                # Empty-table notices are not zero-valued dividend events.
                if len(row) != len(headers):
                    if any('暂无' in c[0] for c in row):
                        continue
                    raise FundDataError(502, '公开分红表格结构异常')
                values = {h: row[headers.index(h)][0] for h in required}
                match = re.fullmatch(r'每10份派现金([\d.]+)元', values['每10份分红'])
                if not match:
                    raise FundDataError(502, '公开分红缺少可核对的每10份现金口径')
                items.append(FundDividend(per_ten_cash_before_tax=number(match[1]),
                    registration_date=day(values['权益登记日']), ex_dividend_date=day(values['除息日']),
                    payment_date=day(values['分红发放日']), progress='公开披露'))
        if not found:
            raise FundDataError(502, '公开分红表头已变化，本次结果未采用')
        return FundDividendsResponse(**self.parent.meta(ticker), items=items,
            warnings=['每10份现金分红，非每份；公开页面未提供公告日、税后口径和完整性证明。不自动据此计算复权净值或总回报。'])

    def holdings(self, ticker, asset_type='stock', report_date=None):
        from app.custom.funds.fallback import Table

        params = {'type': 'zqcc' if asset_type == 'bond' else 'jjcc', 'code': ticker[:6], 'topline': 10}
        if report_date:
            params['year'] = report_date[:4]
        raw = self.parent.http.get('https://fundf10.eastmoney.com/FundArchivesDatas.aspx', params).text
        match = re.search(r'content\s*:\s*("(?:\\.|[^"\\])*")', raw, re.S)
        if not match:
            raise FundDataError(502, '公开持仓页面格式已变化')
        html = json.loads(match[1])
        tables = list(re.finditer(r'<table\b.*?</table>', html, re.S))
        selected = None
        items = []
        for index, table in enumerate(tables):
            prefix = html[tables[index - 1].end() if index else 0:table.start()]
            report = re.search(r'截止至[：:]\s*(?:<[^>]*>\s*)*(\d{4}-\d{2}-\d{2})', prefix)
            if not report:
                raise FundDataError(502, '公开持仓缺少报告期，未采用本次结果')
            period = day(report[1])
            if report_date and period != report_date:
                continue
            selected = period
            parser = Table()
            parser.feed(table[0])
            headers = [c[0] for c in parser.rows[0]]
            code_label, name_label = ('债券代码', '债券名称') if asset_type == 'bond' else ('股票代码', '股票名称')
            required = [code_label, name_label, '占净值比例']
            if not all(h in headers for h in required):
                raise FundDataError(502, '公开持仓表头已变化')
            for row in parser.rows[1:]:
                if len(row) != len(headers):
                    raise FundDataError(502, '公开持仓行结构异常')
                code, name, weight = (row[headers.index(h)][0] for h in required)
                if not re.fullmatch(r'\d{5,6}', code) or not weight.endswith('%'):
                    raise FundDataError(502, '公开持仓代码或比例口径异常')
                links = ' '.join(row[headers.index(code_label)][1])
                market = re.search(r'/unify/r/(0|1|116)\.' + code + r'\b', links)
                # Keep five-digit positions, but only add a market when the
                # source's security link explicitly supplies its identity.
                suffix = '.' + {'0': 'SZ', '1': 'SH', '116': 'HK'}[market[1]] if market else ''
                items.append(FundHolding(ticker=code + suffix, name=name, asset_type=asset_type,
                    weight_pct=number(weight[:-1]), report_date=selected))
            break
        return FundHoldingsResponse(**self.parent.meta(ticker), items=items, report_date=selected,
            scope='public_disclosed_subset', warnings=[
                '公开页面披露的持仓子集，不保证完整；报告期不是公告日，公告日与资产配置比例保持未知。',
                *(['所选报告期暂无公开记录，不代表该期没有持仓。'] if not items else [])])
