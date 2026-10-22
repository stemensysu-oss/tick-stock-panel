"""Review regressions: synthetic responses prove filtering and safe failures."""
import json
from types import SimpleNamespace

import pytest

from app.custom.funds.fallback import EastmoneyFundProvider, FallbackFundProvider
from app.custom.funds.models import FundProfile, FundProfileResponse
from app.custom.funds.service import FundDataError
from app.data_providers.research_market import ResearchSourceError


def test_latest_stock_selection_filters_mixed_primary_holdings_without_public_request():
    from test_custom_funds import _ms, _provider

    provider, requests, _ = _provider({'code': 0, 'data': {'item': [
        {'thscode': '00700.HK', 'stock_name': '合成股票', 'asset_type': 'stock',
         'hold_ratio': 0.12, 'end_date_ms': _ms('2026-06-30')},
        {'thscode': '019827.SH', 'stock_name': '合成债券', 'asset_type': 'bond',
         'hold_ratio': 8, 'end_date_ms': _ms('2026-06-30')},
    ]}})

    def no_public(*args):
        raise AssertionError('A usable primary stock result must keep source priority')

    result = FallbackFundProvider(primary=provider, key_getter=lambda: '',
        fallback=SimpleNamespace(holdings_history=no_public)).holdings_history('000001.OF', 'stock')
    assert [item.ticker for item in result.items] == ['00700.HK']
    assert result.items[0].weight_pct == 0.12
    assert result.report_date == '2026-06-30'
    assert requests[0].url.path == '/api/fund/portfolio/holdings'
    assert result.attempts[-1]['provider'] == 'fuyao'


def test_money_income_public_timeout_uses_safe_source_error_boundary():
    def unavailable(*args):
        raise ResearchSourceError('private-path-and-credential-must-not-escape')

    public = SimpleNamespace(
        profile=lambda *args: FundProfileResponse(ticker='000009.OF', provider='public',
            profile=FundProfile(series_kind='money')),
        nav=unavailable,
    )
    with pytest.raises(FundDataError) as error:
        FallbackFundProvider(fallback=public, key_getter=lambda: '').nav('000009.OF', 'week')
    assert error.value.status_code == 502
    assert 'private-path' not in str(error.value)


def test_money_income_public_timeout_is_a_retryable_api_error(monkeypatch):
    from test_custom_funds import _client

    def unavailable(*args):
        raise ResearchSourceError('sensitive-source-details')

    public = SimpleNamespace(
        profile=lambda *args: FundProfileResponse(ticker='000009.OF', provider='public',
            profile=FundProfile(series_kind='money')),
        nav=unavailable,
    )
    client = _client(monkeypatch, FallbackFundProvider(fallback=public, key_getter=lambda: ''))
    response = client.get('/api/ext/funds/000009.OF/nav?range=week')
    assert response.status_code == 502
    assert '稍后重试' in response.json()['detail']
    assert 'sensitive-source-details' not in response.text


@pytest.mark.parametrize('with_filter', [False, True])
def test_public_stock_holdings_preserve_five_digit_hk_identity(with_filter):
    from test_fund_enrichment import HTTP

    html = ('截止至：<font>2026-06-30</font><table><tr><th>股票代码</th><th>股票名称</th>'
        '<th>占净值比例</th></tr><tr><td><a href="//quote.eastmoney.com/unify/r/116.00700">'
        '00700</a></td><td>合成港股</td><td>0.12%</td></tr></table>')
    raw = 'var apidata={content:' + json.dumps(html) + ',arryear:[2026]};'
    source = EastmoneyFundProvider(HTTP(lambda *args: raw))
    result = source.holdings_history('000001.OF', 'stock') if with_filter else source.holdings('000001.OF')
    assert [item.ticker for item in result.items] == ['00700.HK']
    assert result.items[0].report_date == '2026-06-30'
    assert result.items[0].publish_date is None


def test_public_holdings_does_not_guess_hk_market_from_five_digits():
    from test_fund_enrichment import HTTP

    html = ('截止至：<font>2026-06-30</font><table><tr><th>股票代码</th><th>股票名称</th>'
        '<th>占净值比例</th></tr><tr><td>00700</td><td>合成资产</td><td>0.12%</td></tr></table>')
    raw = 'var apidata={content:' + json.dumps(html) + ',arryear:[2026]};'
    result = EastmoneyFundProvider(HTTP(lambda *args: raw)).holdings('000001.OF')
    assert result.items[0].ticker == '00700'


DIVIDEND_HEADERS = ('<table><tr><th>年份</th><th>权益登记日</th><th>除息日</th>'
    '<th>每10份分红</th><th>分红发放日</th></tr>')


@pytest.mark.parametrize('body', ['', '<tr><td colspan="5">暂无数据，请稍后再试</td></tr>'])
def test_public_dividend_header_only_or_ambiguous_notice_is_not_valid_empty(body):
    from test_fund_enrichment import HTTP

    html = '<title>合成基金(510300)</title>' + DIVIDEND_HEADERS + body + '</table>'
    source = EastmoneyFundProvider(HTTP(lambda *args: html))
    with pytest.raises(FundDataError, match='分红') as error:
        source.dividends('510300.SH')
    assert error.value.status_code == 502


def test_public_dividend_observed_empty_marker_remains_an_explicit_empty_dataset():
    from test_fund_enrichment import HTTP

    html = ('<title>合成基金(000009)</title>' + DIVIDEND_HEADERS
        + '<tr><td colspan="5">暂无分红信息!</td></tr></table>')
    result = EastmoneyFundProvider(HTTP(lambda *args: html)).dividends('000009.OF')
    assert result.items == []


@pytest.mark.parametrize('contradiction', [
    '<label>2026年度 合成基金 累计分红0.123元/份。</label>',
    (DIVIDEND_HEADERS + '<tr><td>2026年</td><td>2026-01-16</td><td>2026-01-19</td>'
     '<td>每10份派现金1.2300元</td><td>2026-01-27</td></tr></table>'),
])
def test_public_dividend_empty_marker_cannot_hide_positive_summary_or_event(contradiction):
    from test_fund_enrichment import HTTP

    html = ('<title>合成基金(510300)</title>' + contradiction + DIVIDEND_HEADERS
        + '<tr><td colspan="5">暂无分红信息!</td></tr></table>')
    with pytest.raises(FundDataError, match='分红'):
        EastmoneyFundProvider(HTTP(lambda *args: html)).dividends('510300.SH')


@pytest.mark.parametrize('cash', ['.', '1..2'])
def test_public_dividend_invalid_decimal_is_a_safe_data_error(cash):
    from test_fund_enrichment import HTTP

    html = ('<title>合成基金(510300)</title>' + DIVIDEND_HEADERS
        + '<tr><td>2026年</td><td>2026-01-16</td><td>2026-01-19</td>'
        + f'<td>每10份派现金{cash}元</td><td>2026-01-27</td></tr></table>')
    with pytest.raises(FundDataError, match='每10份现金'):
        EastmoneyFundProvider(HTTP(lambda *args: html)).dividends('510300.SH')


@pytest.mark.parametrize(('body', 'status'), [
    ('', 502), ('<tr><td colspan="5">暂无分红信息!</td></tr>', 200),
])
def test_dividend_api_distinguishes_malformed_empty_from_explicit_no_record(monkeypatch, body, status):
    from test_custom_funds import _client
    from test_fund_enrichment import HTTP

    html = '<title>合成基金(000009)</title>' + DIVIDEND_HEADERS + body + '</table>'
    source = FallbackFundProvider(fallback=EastmoneyFundProvider(HTTP(lambda *args: html)), key_getter=lambda: '')
    response = _client(monkeypatch, source).get('/api/ext/funds/000009.OF/dividends')
    assert response.status_code == status
    if status == 200:
        assert response.json()['items'] == []
    else:
        assert 'detail' in response.json()
        assert '<title>' not in response.text
