"""Financial semantics, source priority, parser failures. All fixtures are synthetic."""
import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.custom.funds.fallback import EastmoneyFundProvider, FallbackFundProvider
from app.custom.funds.models import FundDividend, FundDividendsResponse
from app.custom.funds.service import FundDataError
from app.data_providers.research_market import SH


class HTTP:
    def __init__(self, handler): self.handler = handler
    def get(self, url, params=None):
        value = self.handler(url, params)
        return httpx.Response(200, json=value) if isinstance(value, dict) else httpx.Response(200, text=value)


def profile(kind):
    return f'<table class="info w790"><tr><th>基金代码</th><td>000009（前端）</td><th>基金全称</th><td>合成基金</td></tr><tr><th>基金类型</th><td>{kind}</td></tr></table>'


def test_money_income_never_becomes_unit_or_cumulative_nav():
    today = datetime.now(SH).date().isoformat()
    def handler(url, params):
        if 'jbgk' in url:
            return profile('货币型-普通货币')
        return {'ErrCode': 0, 'TotalCount': 1, 'Data': {'LSJZList': [
            {'FSRQ': today, 'DWJZ': '0.3109', 'LJJZ': '1.1430', 'NAVTYPE': '1'}]}}
    result = EastmoneyFundProvider(HTTP(handler)).nav('000009.OF', 'week')
    assert result.series_kind == 'money'
    point = result.items[0]
    assert point.unit_nav is point.adj_nav is point.cumulative_nav is None
    assert point.income_per_10000 == 0.3109
    assert point.seven_day_yield_pct == 1.143  # percentage points, NOT 0.01143


def test_unknown_type_fails_closed_and_navtype_is_not_classification():
    with pytest.raises(Exception, match='基金类型'):
        EastmoneyFundProvider(HTTP(lambda *a: profile(''))).nav('000009.OF', 'week')


def test_trading_limits_require_explicit_units_and_unlimited_text():
    html = '<title>合成基金(000009)</title><table><tr><th>申购状态</th><td>限大额</td><th>赎回状态</th><td>开放赎回</td></tr><tr><th>日累计申购限额</th><td>1,000.00元</td><th>申购起点</th><td>10.00元</td></tr><tr><th>最小赎回份额</th><td>---份</td><th>部分赎回最低保留份额</th><td>无限额</td></tr></table>'
    result = EastmoneyFundProvider(HTTP(lambda *a: html)).trading('000009.OF')
    assert result.daily_purchase_limit.value == 1000
    assert result.daily_purchase_limit.status == 'finite'
    assert result.minimum_remaining.status == 'unlimited'
    assert result.minimum_redemption.status == 'unknown'
    assert result.effective_date is None
    bad = html.replace('1,000.00元', '100000000000')
    assert EastmoneyFundProvider(HTTP(lambda *a: bad)).trading('000009.OF').daily_purchase_limit.status == 'unknown'


def test_dividend_per_ten_date_and_empty_are_distinct_from_parser_failure():
    html = '<title>合成(000009)</title><table><tr><th>权益登记日</th><th>除息日</th><th>每10份分红</th><th>分红发放日</th></tr><tr><td>2026-01-16</td><td>2026-01-19</td><td>每10份派现金1.2300元</td><td>2026-01-27</td></tr></table>'
    result = EastmoneyFundProvider(HTTP(lambda *a: html)).dividends('000009.OF')
    assert result.items[0].per_ten_cash_before_tax == 1.23
    assert result.items[0].ex_dividend_date == '2026-01-19'
    assert result.items[0].publish_date is None
    with pytest.raises(FundDataError):
        EastmoneyFundProvider(HTTP(lambda *a: '<html>变更</html>')).dividends('000009.OF')


def test_bond_holdings_report_filter_scope_and_no_guessed_exchange():
    html = '截止至：<font>2026-06-30</font><table><tr><th>债券代码</th><th>债券名称</th><th>占净值比例</th></tr><tr><td>019827</td><td>合成国债</td><td>7.05%</td></tr></table>'
    raw = 'var apidata={content:' + json.dumps(html) + ',arryear:[2026]};'
    source = EastmoneyFundProvider(HTTP(lambda *a: raw))
    result = source.holdings_history('000009.OF', 'bond', '2026-06-30')
    assert result.items[0].ticker == '019827'
    assert result.items[0].asset_type == 'bond'
    assert result.items[0].weight_pct == 7.05
    assert result.items[0].publish_date is None
    assert not source.holdings_history('000009.OF', 'bond', '2026-03-31').items


def test_new_dataset_primary_success_does_not_call_public():
    value = FundDividendsResponse(ticker='000009.OF', provider='fuyao', items=[FundDividend(per_ten_cash_before_tax=1)])
    def fail(*a): raise AssertionError('Public source must not be requested')
    result = FallbackFundProvider(primary=SimpleNamespace(dividends=lambda *a: value), fallback=SimpleNamespace(dividends=fail), key_getter=lambda: '').dividends('000009.OF')
    assert result.provider == 'fuyao'


def test_fuyao_new_endpoints_preserve_dates_units_and_report_parameters():
    from test_custom_funds import _ms, _provider

    from app.custom.funds.provider import FuyaoFundProvider

    provider, requests, _ = _provider({'code': 0, 'data': {'item': [{
        'per_ten_cash_before_tax': 0.12, 'registration_date_ms': _ms('2026-06-29'),
        'ex_dividend_date_ms': _ms('2026-06-30'), 'publish_date_ms': _ms('2026-06-20'),
        'payment_date_ms': _ms('2026-07-03'), 'progress': '实施'}]}})
    result = provider.dividends('510300.SH')
    assert result.items[0].per_ten_cash_before_tax == 0.12
    assert result.items[0].publish_date == '2026-06-20'
    assert requests[0].url.path == '/api/fund/corporate-actions/dividends'
    provider, requests, _ = _provider({'code': 0, 'data': {'item': [{
        'thscode': '019827.SH', 'name': '合成国债', 'asset_type': 'bond',
        'hold_ratio': 0.12, 'end_date_ms': _ms('2026-06-30')}]}})
    result = provider.holdings_history('000001.OF', 'bond', '2026-06-30')
    assert result.items[0].weight_pct == 0.12
    assert result.items[0].publish_date is None
    assert requests[0].url.path == '/api/fund/portfolio/bond-history'
    assert dict(requests[0].url.params) == {'thscode': '000001.OF', 'report_type': 'quarter', 'end_date': '2026-06-30'}
    with pytest.raises(NotImplementedError):
        FuyaoFundProvider('').trading('000001.OF')


@pytest.mark.parametrize('period', ['2026-02-28', '../x', '2026-06-31', '20260630'])
def test_holdings_api_rejects_invalid_report_period_without_network(period):
    from app.custom.funds.service import FundResearchService
    with pytest.raises(FundDataError, match='报告期'):
        FundResearchService(SimpleNamespace()).holdings('000001.OF', 'bond', period)


def test_money_unknown_navtype_is_rejected_instead_of_guessing():
    today = datetime.now(SH).date().isoformat()
    def handler(url, params):
        if 'jbgk' in url:
            return profile('货币型-普通货币')
        return {'ErrCode': 0, 'TotalCount': 1, 'Data': {'LSJZList': [
            {'FSRQ': today, 'DWJZ': '1.0', 'LJJZ': '1.1430', 'NAVTYPE': '2'}]}}
    with pytest.raises(FundDataError, match='字段类型'):
        EastmoneyFundProvider(HTTP(handler)).nav('000009.OF', 'week')
