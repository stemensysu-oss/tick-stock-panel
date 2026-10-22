"""Read-only sourced terms; never overwrite manual research or invent cash flows.

Neither integrated original API documents full bond terms/call disclosures.
The public datacenter is a secondary compilation, not an issuer announcement.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from app.data_providers.research_market import PUBLIC, SH, PublicHTTP, number
from app.services.convertibles_sources import ConvertibleDataError, normalize_symbol


class ConvertibleDateEvent(BaseModel):
    type: str
    start_date: str | None = None
    end_date: str | None = None


class ConvertibleDisclosures(BaseModel):
    code: str
    name: str
    provider: str = PUBLIC
    fetched_at: str
    source_url: str
    attempts: list[dict] = Field(default_factory=lambda: [
        {'provider': 'tickflow', 'status': 'unsupported'},
        {'provider': 'fuyao', 'status': 'unsupported'},
        {'provider': PUBLIC, 'status': 'success'}])
    lifecycle: Literal['listed', 'terminated', 'not_yet_listed', 'unknown'] = 'unknown'
    listing_date: str | None = None
    delisting_date: str | None = None
    source_end_date: str | None = None
    interest_start_date: str | None = None
    conversion_start_date: str | None = None
    conversion_end_date: str | None = None
    reference_conversion_price: float | None = None
    par_value: float | None = None
    rating: str | None = None
    rating_agency: str | None = None
    coupon_text: str | None = None
    call_clause_text: str | None = None
    put_clause_text: str | None = None
    call_state: Literal['implementation_disclosed', 'historical_implementation', 'unknown'] = 'unknown'
    call_notice_date: str | None = None
    call_record_date: str | None = None
    call_execution_date: str | None = None
    call_price: float | None = None
    put_notice_date: str | None = None
    put_execution_start: str | None = None
    put_execution_end: str | None = None
    put_price: float | None = None
    events: list[ConvertibleDateEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: 00:00:00)?', value):
        raise ValueError('Invalid disclosure date')
    return date.fromisoformat(value[:10]).isoformat()


class ConvertibleDisclosureProvider:
    def __init__(self, http=None):
        self.http = http or PublicHTTP()

    def fetch(self, code, today=None):
        symbol = normalize_symbol(code, kind='bond')
        code = symbol[:6]
        now = datetime.now(SH)
        today = today or now.date().isoformat()
        def fetch(report):
            response = self.http.get('https://datacenter-web.eastmoney.com/api/data/v1/get', {
                'reportName': report, 'columns': 'ALL',
                'filter': f'(SECURITY_CODE="{code}")', 'pageSize': 100, 'pageNumber': 1,
            }).json()
            result = response.get('result') or {}
            rows = result.get('data')
            if response.get('success') is not True or not isinstance(rows, list) or result.get('count') != len(rows):
                raise ValueError('Incomplete bond disclosures')
            if any(row.get('SECURITY_CODE') != code for row in rows):
                raise ValueError('Bond identity mismatch')
            return rows
        rows = fetch('RPT_BOND_CB_LIST')
        if len(rows) != 1 or rows[0].get('SECUCODE') != symbol or not rows[0].get('SECURITY_NAME_ABBR'):
            raise ValueError('No matching bond terms')
        row = rows[0]
        listed, ended = _date(row.get('LISTING_DATE')), _date(row.get('DELIST_DATE'))
        source_end = _date(row.get('EXPIRE_DATE'))
        lifecycle = ('terminated' if (ended and ended <= today) or (source_end and source_end <= today)
            else 'not_yet_listed' if listed and listed > today else 'listed' if listed else 'unknown')
        notice, execution = _date(row.get('NOTICE_DATE_SH')), _date(row.get('EXECUTE_START_DATESH'))
        state = ('historical_implementation' if lifecycle == 'terminated' else 'implementation_disclosed') if (
            notice and notice <= today and execution and number(row.get('EXECUTE_PRICE_SH'), positive=True) is not None) else 'unknown'
        warnings = [
            '公开汇编资料，须通过发行人或交易所最新公告复核；获取时间不是公告时间。',
            '赎回权条款、价格条件达标、决定不赎回、正式实施属于不同状态。缺少逐日有效转股价与完整观察记录，不推算强赎计数。',
            '源结束日期可能含提前终止，不冒充原始合同到期日；票息文字不自动生成完整现金流或YTM。',
            '联网资料独立展示，不覆盖已保存的人工条款、公告、现金流和估值参数。',
        ]
        if lifecycle == 'terminated':
            warnings.append('该债券已经终止/退市，历史实施记录不代表当前可交易；原计划付息字段不作为未来应收现金流。')
        events = []
        try:
            for event in fetch('RPT_CB_IMPORTANTDATE'):
                if not event.get('DATE_TYPE'):
                    raise ValueError('No event type')
                events.append(ConvertibleDateEvent(type=str(event['DATE_TYPE']),
                    start_date=_date(event.get('START_DATE')), end_date=_date(event.get('END_DATE'))))
        except Exception:  # noqa: BLE001 -- partial dataset is explicit, never a silent success
            warnings.append('重要日期接口本次未返回完整数据，条款快照仍可独立查看。')
        return ConvertibleDisclosures(code=code, name=row['SECURITY_NAME_ABBR'],
            fetched_at=now.isoformat(timespec='seconds'), source_url=f'https://data.eastmoney.com/kzz/detail/{code}.html',
            lifecycle=lifecycle, listing_date=listed, delisting_date=ended, source_end_date=source_end,
            interest_start_date=_date(row.get('VALUE_DATE')),
            conversion_start_date=_date(row.get('TRANSFER_START_DATE')), conversion_end_date=_date(row.get('TRANSFER_END_DATE')),
            reference_conversion_price=number(row.get('TRANSFER_PRICE'), positive=True),
            par_value=number(row.get('PAR_VALUE'), positive=True), rating=row.get('RATING'), rating_agency=row.get('PARTY_NAME'),
            coupon_text=row.get('INTEREST_RATE_EXPLAIN'), call_clause_text=row.get('REDEEM_CLAUSE'), put_clause_text=row.get('RESALE_CLAUSE'),
            call_state=state, call_notice_date=notice, call_record_date=_date(row.get('RECORD_DATE_SH')),
            call_execution_date=execution, call_price=number(row.get('EXECUTE_PRICE_SH'), positive=True),
            put_notice_date=_date(row.get('NOTICE_DATE_HS')), put_execution_start=_date(row.get('EXECUTE_START_DATEHS')),
            put_execution_end=_date(row.get('EXECUTE_END_DATE')), put_price=number(row.get('EXECUTE_PRICE_HS'), positive=True),
            events=events, warnings=warnings)


@lru_cache(maxsize=128)
def _cached(symbol, bucket):
    return ConvertibleDisclosureProvider().fetch(symbol)


def disclosures(code):
    symbol = normalize_symbol(code, kind='bond')
    try:
        return _cached(symbol, int(time.monotonic() // 300)).model_copy(deep=True)
    except Exception:  # noqa: BLE001 -- redact source errors
        raise ConvertibleDataError(502, '公开条款/强赎资料暂不可用或代码不匹配，原研究资料未更改') from None
