"""Bounded dividend/IPO events, separate from prices and user imports.

Fuyao IPO contract: https://fuyao.aicubes.cn/docs/api-reference/a-share-ipo/
Public source: https://data.eastmoney.com/yjfp/ and /xg/xg/default.html.
The source's PRETAX_BONUS_RMB is CNY per TEN shares, confirmed by its plan
description. We do not turn one plan into a TTM dividend or a realized yield.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from app.data_providers.research_market import (
    SH,
    PublicHTTP,
    ResearchSourceError,
    number,
)
from app.services.multi_asset_models import AssetInput

logger = logging.getLogger(__name__)
PUBLIC = 'eastmoney_events_public'
EVENT_CATEGORIES = frozenset({'dividends', 'ipo'})
_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
_LIMIT = 1000
_PAGE_SIZE = 100


@dataclass
class EventRows:
    rows: list[AssetInput]
    metadata: list[dict]
    warnings: list[str] = field(default_factory=list)


@dataclass
class EventBatch:
    rows: list[AssetInput]
    fetched_at: str
    attempts: list[dict]
    warnings: list[str] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)


def _date(value, *, required=False):
    if value in (None, '', '-'):
        if required:
            raise ResearchSourceError('事件缺少来源日期')
        return None
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?', value):
        raise ResearchSourceError('事件来源日期格式异常')
    try:
        parsed = datetime.fromisoformat(value) if len(value) > 10 else date.fromisoformat(value)
    except ValueError:
        raise ResearchSourceError('事件来源日期格式异常') from None
    return parsed.date().isoformat() if isinstance(parsed, datetime) else parsed.isoformat()


def _text(value, *, required=False, limit=100):
    if value in (None, '') and not required:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ResearchSourceError('事件来源文字格式异常')
    return value.strip()


def _identity(raw, *, fuyao=False):
    code = raw.get('thscode' if fuyao else 'SECUCODE')
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
        raise ResearchSourceError('事件缺少明确证券代码与市场')
    name = _text(raw.get('name') if fuyao else raw.get('SECURITY_NAME_ABBR')
                 or raw.get('SECURITY_NAME'), required=True)
    return code, name


class EastmoneyEventProvider:
    name = PUBLIC

    def __init__(self, http=None, *, today=None):
        self.http = http or PublicHTTP()
        self.today = today or datetime.now(SH).date()

    def _list(self, category):
        report, sort = (('RPT_SHAREBONUS_DET', 'NOTICE_DATE,SECURITY_CODE')
                        if category == 'dividends'
                        else ('RPTA_APP_IPOAPPLY', 'APPLY_DATE,SECURITY_CODE'))
        filters = ('' if category == 'dividends'
                   else f"(APPLY_DATE>='{self.today - timedelta(days=365)}')")
        output, total, started = [], None, time.monotonic()
        for page in range(1, _LIMIT // _PAGE_SIZE + 1):
            if time.monotonic() - started > 45:
                raise ResearchSourceError('事件分页取数超时，原数据已保留')
            payload = self.http.get(_URL, {
                'reportName': report, 'columns': 'ALL', 'sortColumns': sort,
                'sortTypes': '-1,1', 'pageSize': _PAGE_SIZE, 'pageNumber': page,
                'source': 'WEB', 'client': 'WEB', 'filter': filters,
            }).json()
            result = payload.get('result') if isinstance(payload, dict) else None
            if (payload.get('success') is not True or not isinstance(result, dict)
                    or not isinstance(result.get('data'), list)):
                raise ResearchSourceError('事件补充源返回空清单或格式异常')
            if total is None:
                raw_total = result.get('count')
                if type(raw_total) is not int or not 0 < raw_total < 1000000:
                    raise ResearchSourceError('事件补充源总数异常')
                total = raw_total
            rows = result['data']
            if not rows or len(rows) > _PAGE_SIZE or not all(isinstance(r, dict) for r in rows):
                raise ResearchSourceError('事件分页不完整或格式异常')
            output.extend(rows)
            if len(output) >= min(total, _LIMIT):
                break
        if len(output) != min(total or 0, _LIMIT):
            raise ResearchSourceError('事件分页不完整，原数据已保留')
        return output, total

    def _dividend(self, raw):
        code, name = _identity(raw)
        cash = number(raw.get('PRETAX_BONUS_RMB'), positive=True)
        if cash is None:
            return None
        notice = _date(raw.get('NOTICE_DATE'), required=True)
        if notice > self.today.isoformat():
            raise ResearchSourceError('分红来源公告日异常')
        plan = _date(raw.get('PLAN_NOTICE_DATE'))
        record = _date(raw.get('EQUITY_RECORD_DATE'))
        ex = _date(raw.get('EX_DIVIDEND_DATE'))
        report = _date(raw.get('REPORT_DATE'))
        progress = _text(raw.get('ASSIGN_PROGRESS')) or '进度未披露'
        description = _text(raw.get('IMPL_PLAN_PROFILE'), limit=500)
        # An explicit source ex-date takes precedence. Otherwise show the real
        # plan announcement date, clearly tagged, never an invented ex-date.
        event = ex or plan or notice
        kind = 'ex_dividend_date' if ex else 'plan_notice_date' if plan else 'notice_date'
        notes = [f'方案进度：{progress}；税前人民币每10股金额÷10；预案不是已支付收益。',
                 f'最新公告：{notice}；报告期末：{report or "未披露"}；',
                 f'预案公告：{plan or "未披露"}；登记：{record or "未披露"}；除息：{ex or "未披露"}。',
                 '未提供完整分红期间和当前价格，不计算期间股息率或滚动12个月股息率。']
        if description:
            notes.append(f'来源方案：{description}')
        row = AssetInput(code=code, name=name, currency='CNY',
                         source_name='东方财富公开分红事件',
                         source_url=f'https://data.eastmoney.com/yjfp/detail/{code[:6]}.html',
                         as_of=notice, event_date=event, event_type=f'现金分红：{progress}',
                         dividend_per_share=cash / 10, dividend_currency='CNY',
                         dividend_period_end=report, notes=''.join(notes))
        return row, dict(source_id=self.name, source_updated_date=notice, data_as_of=notice,
                         event_date=event, event_date_kind=kind, progress=progress,
                         plan_notice_date=plan, equity_record_date=record,
                         ex_dividend_date=ex, report_date=report,
                         dividend_tax_basis='pretax', dividend_source_unit='CNY_per_10_shares')

    def _ipo(self, raw):
        code, name = _identity(raw)
        apply = _date(raw.get('APPLY_DATE'), required=True)
        listing = _date(raw.get('LISTING_DATE') or raw.get('SELECT_LISTING_DATE'))
        updated = _date(raw.get('UP_DATE'))
        if updated and updated > self.today.isoformat():
            raise ResearchSourceError('新股来源更新日异常')
        apply_code = _text(raw.get('APPLY_CODE'), limit=16)
        if apply_code is not None and not re.fullmatch(r'\d{6}', apply_code):
            raise ResearchSourceError('新股申购代码格式异常')
        ballot = _date(raw.get('BALLOT_NUM_DATE') or raw.get('RESULT_NOTICE_DATE'))
        pay = _date(raw.get('BALLOT_PAY_DATE') or raw.get('ONLINE_PAY_DATE'))
        today = self.today.isoformat()
        status = ('已上市（日历）' if listing and listing <= today
                  else '待上市（日历）' if listing and listing > today and apply < today
                  else '待申购（日历）' if apply > today
                  else '申购日（日历，非盘中状态）' if apply == today
                  else '申购结束／待上市（日历）')
        row = AssetInput(code=code, name=name, currency='CNY',
                         source_name='东方财富公开新股事件',
                         source_url='https://data.eastmoney.com/xg/xg/default.html',
                         as_of=updated or today, issue_price=number(raw.get('ISSUE_PRICE'), positive=True),
                         event_date=apply, event_type='新股网上申购日', subscription_status=status,
                         notes=(f'申购代码：{apply_code or "未披露"}；申购：{apply}；上市：{listing or "未披露"}；'
                                f'中签/结果：{ballot or "未披露"}；缴款：{pay or "未披露"}。'
                                '状态仅按来源日期与北京时间推导，不验证盘中受理、账户额度或中签。'
                                '未公布发行价保持未知，不采用预测价、最新价代替。'
                                + (f'来源更新日：{updated}。' if updated else
                                   '来源未给更新日，基准日为抓取日；事件日均来自源数据。')))
        return row, dict(source_id=self.name, source_updated_date=updated, data_as_of=updated,
                         event_date=apply, event_date_kind='subscription_date', apply_code=apply_code,
                         subscription_date=apply, listing_date=listing,
                         ballot_num_date=ballot, ballot_pay_date=pay,
                         status_basis='source_dates_calendar_only')

    def events(self, category):
        if category not in EVENT_CATEGORIES:
            raise NotImplementedError
        raw_rows, total = self._list(category)
        rows, metadata, seen, invalid, no_cash = [], [], set(), 0, 0
        for raw in raw_rows:
            try:
                result = self._dividend(raw) if category == 'dividends' else self._ipo(raw)
                if result is None:
                    no_cash += 1
                    continue
                row, info = result
                if row.code in seen:
                    continue
                seen.add(row.code)
                rows.append(row)
                metadata.append(info)
            except (ResearchSourceError, ValidationError, TypeError, ValueError):
                invalid += 1
        if not rows:
            raise ResearchSourceError('事件补充源没有有效记录；原数据已保留')
        warnings = [
            '公开事件来自网站数据中心，可能延迟或修订；不是交易所原始公告的独立核验。',
            ('分红仅展示最新1000条公告中的现金方案、每证券最新一条；不代表完整历史或完整滚动12个月。'
             if category == 'dividends' else
             '新股覆盖已公布申购日期的沪深京新股，含最近365天及未来已排期记录；未知日期的发行不在清单中。'),
        ]
        if total > _LIMIT:
            warnings.append(f'来源共{total}条，本次读取最新{_LIMIT}条；不代表全量历史。')
        if invalid:
            warnings.append(f'{invalid} 条来源记录字段异常，已剔除；未伪造日期、金额或证券市场。')
        if no_cash:
            warnings.append(f'{no_cash} 条没有正值现金分红的送转/空方案未列为现金股息。')
        return EventRows(rows, metadata, warnings)


class TickFlowEventProvider:
    name = 'tickflow'

    def events(self, category):
        # The installed TickFlow client exposes quotes, not a verified full-market
        # dividend-plan/IPO calendar contract. Never guess an endpoint.
        raise NotImplementedError


class FuyaoEventProvider:
    name = 'fuyao'

    def events(self, category):
        if category != 'ipo':
            # Single-security historical adjustment events do not provide an
            # upcoming all-market dividend plan calendar, progress or record dates.
            raise NotImplementedError
        from app.plugins.fuyao.client import FuyaoClient
        from app.plugins.fuyao.provider import get_api_key

        key = get_api_key()
        if not key:
            raise PermissionError
        client = FuyaoClient(key, timeout=8)
        rows, metadata, seen = [], [], set()
        today = datetime.now(SH).date().isoformat()
        stages = {'upcoming': '待申购（来源阶段）', 'subscribable': '可申购（来源阶段）',
                  'awaiting_listing': '待上市（来源阶段）'}
        try:
            for market in ('sh_sz', 'bj'):
                for stage, label in stages.items():
                    data = client._get('/api/a-share/ipo/calendar-list', {'market': market, 'status': stage})
                    if (not isinstance(data, dict) or data.get('market') != market
                            or data.get('status') != stage or not isinstance(data.get('item'), list)):
                        raise ResearchSourceError('扶摇新股日历格式或市场/阶段异常')
                    if len(data['item']) > _LIMIT:
                        raise ResearchSourceError('扶摇新股日历超过记录上限')
                    for raw in data['item']:
                        code, name = _identity(raw, fuyao=True)
                        if (market == 'bj') != code.endswith('.BJ'):
                            raise ResearchSourceError('扶摇新股日历证券市场不匹配')
                        apply = _date(raw.get('subscription_date'))
                        listing = _date(raw.get('listing_date'))
                        if code in seen:
                            raise ResearchSourceError('扶摇新股日历跨阶段存在重复代码，请重试')
                        seen.add(code)
                        row = AssetInput(
                            code=code, name=name, currency='CNY', source_name='扶摇新股发行日历',
                            source_url='https://fuyao.aicubes.cn/docs/api-reference/a-share-ipo/',
                            as_of=today, issue_price=number(raw.get('issue_price'), positive=True),
                            event_date=apply, event_type='新股网上申购日', subscription_status=label,
                            notes=(f'申购代码：{_text(raw.get("subscription_code"), limit=16) or "未披露"}；'
                                   f'申购：{apply or "未披露"}；上市：{listing or "未披露"}。'
                                   '发行阶段由扶摇返回，不验证账户额度或是否仍可盘中申购；'
                                   '源未给记录更新日，基准日为抓取日。'))
                        rows.append(row)
                        metadata.append(dict(
                            source_id=self.name, source_updated_date=None, data_as_of=None,
                            event_date=apply, event_date_kind='subscription_date',
                            apply_code=raw.get('subscription_code'), subscription_date=apply,
                            listing_date=listing, source_stage=stage,
                            status_basis='provider_stage', market=market))
        finally:
            client.close()
        return EventRows(rows, metadata, [
            '扶摇新股日历仅覆盖待申购、可申购和待上市阶段，不含已上市历史；以来源实际返回为准。',
        ])


class ResearchEventsService:
    def __init__(self, providers=None):
        self.providers = providers if providers is not None else [
            TickFlowEventProvider(), FuyaoEventProvider(), EastmoneyEventProvider()]

    def fetch(self, category):
        if category not in EVENT_CATEGORIES:
            raise ResearchSourceError('不支持的事件类别')
        attempts = []
        for provider in self.providers:
            try:
                result = provider.events(category)
                if len(result.rows) != len(result.metadata):
                    raise ResearchSourceError('事件与来源元数据不一致')
                attempts.append(dict(provider=provider.name,
                                     status='success' if result.rows else 'empty', rows=len(result.rows)))
                if result.rows:
                    return EventBatch(result.rows, datetime.now(SH).isoformat(timespec='seconds'),
                                      attempts, result.warnings, result.metadata)
            except NotImplementedError:
                attempts.append(dict(provider=provider.name, status='unsupported'))
            except PermissionError:
                attempts.append(dict(provider=provider.name, status='unconfigured'))
            except Exception as exc:  # noqa: BLE001 -- never expose supplier URLs/keys
                attempts.append(dict(provider=provider.name, status='failed'))
                logger.warning('Research events source failed: provider=%s category=%s type=%s',
                               provider.name, category, type(exc).__name__)
        raise ResearchSourceError('所有可用数据源均未返回有效事件；原数据已保留，请稍后重试')


_CACHE, _LOCK = {}, threading.Lock()


def event_batch(category, *, force=False):
    # Include Shanghai date because source-calendar labels change at midnight.
    key = (category, datetime.now(SH).date().isoformat())
    with _LOCK:
        cached = _CACHE.get(key)
    if cached and not force and time.monotonic() - cached[0] < 300:
        return cached[1]
    result = ResearchEventsService().fetch(category)
    with _LOCK:
        if len(_CACHE) > 4:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), result)
    return result
