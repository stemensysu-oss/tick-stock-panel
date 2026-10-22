"""Event data contracts: plans are not realized dividends or intraday quotes."""
from datetime import date

import httpx
import pytest

from app.data_providers import research_events as events
from app.services.multi_asset import calculate_metrics

TODAY = date(2026, 10, 22)


def dividend(**changes):
    return dict(SECUCODE='003008.SZ', SECURITY_NAME_ABBR='开普检测',
                PRETAX_BONUS_RMB=1.8, REPORT_DATE='2026-09-30 00:00:00',
                PLAN_NOTICE_DATE='2026-10-22 00:00:00',
                NOTICE_DATE='2026-10-22 00:00:00', ASSIGN_PROGRESS='董事会决议通过',
                IMPL_PLAN_PROFILE='10派1.80元(含税)', **changes)


def ipo(**changes):
    raw = dict(SECUCODE='688827.SH', SECURITY_NAME='钶锐锶', APPLY_CODE='787827',
               APPLY_DATE='2026-10-29 00:00:00', LISTING_DATE=None,
               ISSUE_PRICE=None, PREDICT_ISSUE_PRICE=99,
               BALLOT_PAY_DATE='2026-11-02 00:00:00', UP_DATE='2026-10-22 00:00:00')
    raw.update(changes)
    return raw


class HTTP:
    def __init__(self, rows, *, count=None):
        self.rows, self.count, self.calls = rows, count or len(rows), []

    def get(self, url, params):
        self.calls.append((url, params))
        offset = (params['pageNumber'] - 1) * params['pageSize']
        return httpx.Response(200, json=dict(success=True, result=dict(
            count=self.count, pages=(self.count + 99) // 100,
            data=self.rows[offset:offset + params['pageSize']])))


def test_dividend_per_ten_becomes_pretax_per_share_without_invented_yield():
    feed = events.EastmoneyEventProvider(HTTP([dividend()]), today=TODAY).events('dividends')
    row, info = feed.rows[0], feed.metadata[0]
    assert row.dividend_per_share == pytest.approx(.18)
    assert row.dividend_currency == 'CNY'
    assert row.price is None and row.dividend_basis is None and row.dividend_period_start is None
    assert row.dividend_period_end == '2026-09-30'
    assert row.event_date == '2026-10-22'
    assert info['event_date_kind'] == 'plan_notice_date'
    assert info['progress'] == '董事会决议通过'
    assert '税前' in row.notes and '不是已支付收益' in row.notes
    assert calculate_metrics('dividends', row)[0]['dividend_yield_pct'] is None


def test_implementation_still_preserves_future_ex_date_and_distinct_record_date():
    raw = dividend()
    raw.update(ASSIGN_PROGRESS='实施分配', EX_DIVIDEND_DATE='2026-10-28 00:00:00',
               EQUITY_RECORD_DATE='2026-10-27 00:00:00')
    result = events.EastmoneyEventProvider(HTTP([raw]), today=TODAY).events('dividends')
    assert result.rows[0].event_date == '2026-10-28'
    assert result.metadata[0]['equity_record_date'] == '2026-10-27'
    assert result.metadata[0]['event_date_kind'] == 'ex_dividend_date'
    assert result.rows[0].as_of == '2026-10-22'


def test_ipo_unannounced_price_is_not_replaced_with_prediction_or_latest_price():
    result = events.EastmoneyEventProvider(HTTP([ipo()]), today=TODAY).events('ipo')
    row = result.rows[0]
    assert row.issue_price is None and row.price is None
    assert row.event_date == '2026-10-29'
    assert row.subscription_status == '待申购（日历）'
    assert result.metadata[0]['apply_code'] == '787827'
    assert result.metadata[0]['ballot_pay_date'] == '2026-11-02'


@pytest.mark.parametrize('apply,listing,status', [
    ('2026-10-22', None, '申购日（日历，非盘中状态）'),
    ('2026-10-19', None, '申购结束／待上市（日历）'),
    ('2026-09-15', '2026-10-01', '已上市（日历）'),
    ('2026-10-19', '2026-10-27', '待上市（日历）'),
])
def test_ipo_status_uses_calendar_and_never_claims_broker_eligibility(apply, listing, status):
    raw = ipo(APPLY_DATE=apply, LISTING_DATE=listing, ISSUE_PRICE=12.5)
    row = events.EastmoneyEventProvider(HTTP([raw]), today=TODAY).events('ipo').rows[0]
    assert row.subscription_status == status
    assert row.issue_price == 12.5


def test_bj_ipo_and_missing_source_update_date_remain_explicit():
    raw = ipo(SECUCODE='920306.BJ', UP_DATE=None, APPLY_DATE='2026-10-20', ISSUE_PRICE=4.48)
    result = events.EastmoneyEventProvider(HTTP([raw]), today=TODAY).events('ipo')
    assert result.rows[0].code == '920306.BJ'
    assert result.rows[0].as_of == TODAY.isoformat()
    assert result.metadata[0]['source_updated_date'] is None
    assert '基准日为抓取日' in result.rows[0].notes


def test_dividends_latest_per_security_keep_latest_plan_and_count_omissions():
    old = dividend()
    old.update(PRETAX_BONUS_RMB=10, REPORT_DATE='2025-12-31', NOTICE_DATE='2026-10-21')
    result = events.EastmoneyEventProvider(HTTP([dividend(), old]), today=TODAY).events('dividends')
    assert len(result.rows) == 1 and result.rows[0].dividend_per_share == pytest.approx(.18)
    assert any('最新一条' in warning for warning in result.warnings)


def test_bad_individual_records_excluded_and_bad_source_date_never_invented():
    bad = dividend()
    bad.update(NOTICE_DATE='2026-99-42')
    result = events.EastmoneyEventProvider(HTTP([bad, dividend()]), today=TODAY).events('dividends')
    assert len(result.rows) == 1
    assert any('1 条' in warning and '异常' in warning for warning in result.warnings)


def test_no_cash_stock_bonus_or_missing_explicit_security_market_not_misclassified():
    raw = dividend()
    raw.update(PRETAX_BONUS_RMB=0, BONUS_RATIO=2)
    with pytest.raises(events.ResearchSourceError):
        events.EastmoneyEventProvider(HTTP([raw]), today=TODAY).events('dividends')
    with pytest.raises(events.ResearchSourceError):
        events.EastmoneyEventProvider(HTTP([ipo(SECUCODE=None)]), today=TODAY).events('ipo')


def test_pagination_follows_source_count_and_ipo_filter_is_explicit():
    raws = [ipo(SECUCODE=f'{600000+i:06}.SH') for i in range(101)]
    http = HTTP(raws)
    result = events.EastmoneyEventProvider(http, today=TODAY).events('ipo')
    assert len(result.rows) == 101
    assert [call[1]['pageNumber'] for call in http.calls] == [1, 2]
    assert http.calls[0][1]['filter'] == "(APPLY_DATE>='2025-10-22')"


def test_interrupted_pagination_rejects_partial_snapshot():
    with pytest.raises(events.ResearchSourceError, match='分页'):
        events.EastmoneyEventProvider(HTTP([ipo()], count=101), today=TODAY).events('ipo')


def test_bounded_latest_announcements_are_disclosed():
    raws = []
    for n in range(1000):
        raw = dividend()
        raw['SECUCODE'] = f'{600000+n:06}.SH'
        raws.append(raw)
    http = HTTP(raws, count=1001)
    result = events.EastmoneyEventProvider(http, today=TODAY).events('dividends')
    assert len(result.rows) == 1000 and len(http.calls) == 10
    assert any('1000' in warning and '不代表' in warning for warning in result.warnings)


def test_default_provider_priority_and_primary_calendar_unsupported_are_visible(monkeypatch):
    monkeypatch.setattr('app.plugins.fuyao.provider.get_api_key', lambda: '')
    public = events.EventRows([], [], [])
    public.rows = events.EastmoneyEventProvider(HTTP([ipo()]), today=TODAY).events('ipo').rows
    public.metadata = [{'source_id': events.PUBLIC}]
    monkeypatch.setattr(events.EastmoneyEventProvider, 'events', lambda *args: public)
    batch = events.ResearchEventsService().fetch('ipo')
    assert [(a['provider'], a['status']) for a in batch.attempts] == [
        ('tickflow', 'unsupported'), ('fuyao', 'unconfigured'), (events.PUBLIC, 'success')]


def test_fuyao_documented_ipo_calendar_precedes_public_and_keeps_null_dates(monkeypatch):
    calls, closed = [], []
    class Client:
        def __init__(self, key, timeout):
            assert key == 'test-key' and timeout == 8
        def _get(self, path, params):
            calls.append((path, params))
            rows = ([dict(thscode='920285.BJ', name='远大健科', subscription_code='920285',
                          subscription_date='2026-10-14', listing_date=None, issue_price=20.3)]
                    if params == dict(market='bj', status='awaiting_listing') else [])
            return {**params, 'item': rows}
        def close(self):
            closed.append(True)
    monkeypatch.setattr('app.plugins.fuyao.provider.get_api_key', lambda: 'test-key')
    monkeypatch.setattr('app.plugins.fuyao.client.FuyaoClient', Client)
    result = events.FuyaoEventProvider().events('ipo')
    assert len(calls) == 6 and len(closed) == 1
    assert {call[0] for call in calls} == {'/api/a-share/ipo/calendar-list'}
    row, info = result.rows[0], result.metadata[0]
    assert row.code == '920285.BJ' and row.issue_price == 20.3
    assert row.event_date == '2026-10-14' and info['listing_date'] is None
    assert info['data_as_of'] is None and info['source_updated_date'] is None
    assert row.subscription_status == '待上市（来源阶段）'


def test_fuyao_dividend_plan_calendar_is_unsupported_not_historical_adjustments():
    with pytest.raises(NotImplementedError):
        events.FuyaoEventProvider().events('dividends')


def test_fuyao_no_key_fails_before_any_request(monkeypatch):
    monkeypatch.setattr('app.plugins.fuyao.provider.get_api_key', lambda: '')
    with pytest.raises(PermissionError):
        events.FuyaoEventProvider().events('ipo')


def test_successful_primary_never_calls_public_and_supplier_exception_not_exposed():
    rows = events.EastmoneyEventProvider(HTTP([ipo()]), today=TODAY).events('ipo')
    class First:
        name = 'tickflow'
        def events(self, category):
            return rows
    class Never:
        name = 'fuyao'
        def events(self, category):
            raise AssertionError('must not request another source')
    result = events.ResearchEventsService([First(), Never()]).fetch('ipo')
    assert len(result.attempts) == 1
    class Broken:
        name = 'tickflow'
        def events(self, category):
            raise RuntimeError('secret-token')
    with pytest.raises(events.ResearchSourceError) as exc:
        events.ResearchEventsService([Broken()]).fetch('ipo')
    assert 'secret-token' not in str(exc.value)


def test_cache_force_refresh_failed_refresh_preserves_previous_snapshot(monkeypatch):
    events._CACHE.clear()
    data = events.EventBatch([], '2026-10-22T10:00:00+08:00', [], [], [])
    calls = []
    def fetch(self, category):
        calls.append(category)
        if len(calls) > 1:
            raise events.ResearchSourceError('offline')
        return data
    monkeypatch.setattr(events.ResearchEventsService, 'fetch', fetch)
    assert events.event_batch('ipo') is data
    assert events.event_batch('ipo') is data
    with pytest.raises(events.ResearchSourceError):
        events.event_batch('ipo', force=True)
    assert events.event_batch('ipo') is data
    events._CACHE.clear()
