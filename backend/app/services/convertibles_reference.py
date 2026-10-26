"""Read-only, dated reference overlay; never modifies quotes or manual research.

Neither currently integrated primary API has a documented CB valuation/terms
contract. Public estimates are supplier models, not a locally verified bond floor.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from functools import lru_cache

from pydantic import BaseModel, Field

from app.data_providers.research_market import PUBLIC, SH, PublicHTTP, number, quote_time
from app.services.convertibles_cashflows import contract_cash_flows, contract_redemption_price
from app.services.convertibles_disclosures import _date
from app.services.convertibles_sources import ConvertibleDataError, normalize_symbol

URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
QUOTE_COLUMNS = ','.join(f'{field}~{market}~{code}~{alias}' for field, market, code, alias in (
    ('f2', '10', 'SECURITY_CODE', 'CB_PRICE'), ('f38', '10', 'SECURITY_CODE', 'CB_UNITS'),
    ('f20', '10', 'SECURITY_CODE', 'CB_CAP'), ('f124', '10', 'SECURITY_CODE', 'CB_STAMP'),
    ('f239', '10', 'SECURITY_CODE', 'CB_PUT'), ('f240', '10', 'SECURITY_CODE', 'CB_CALL'),
    ('f23', '01', 'CONVERT_STOCK_CODE', 'STOCK_PB'),
    ('f21', '01', 'CONVERT_STOCK_CODE', 'STOCK_FLOAT_CAP'),
    ('f124', '01', 'CONVERT_STOCK_CODE', 'STOCK_STAMP')))


def _time(value):
    try:
        return quote_time(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _quantity_values(quantity, cap, price, at):
    quantity, cap, price = number(quantity), number(cap), number(price, positive=True)
    if (quantity is None or quantity < 0 or not quantity.is_integer() or price is None or cap is None
            or cap < 0 or abs(cap - quantity * price) > max(2, abs(cap) * 0.00001)):
        return {}
    return dict(outstanding_units=quantity, outstanding_amount=quantity * 100,
        outstanding_observed_at=at, outstanding_as_of=None, quantity_validation_price=price, quantity_market_value=cap,
        outstanding_basis='公开转债存续张数×每张面值100元；数量统计日未披露，以获取时间标注')


class ConvertibleReference(BaseModel):
    code: str
    name: str | None = None
    source: str = PUBLIC
    source_url: str
    fetched_at: str
    maturity_date: str | None = None
    source_end_date: str | None = None
    conversion_end_date: str | None = None
    conversion_start_date: str | None = None
    listing_date: str | None = None
    lifecycle: str = 'unknown'
    stock_code: str | None = None
    interest_start_date: str | None = None
    rating_agency: str | None = None
    credit_rating: str | None = None
    coupon_text: str | None = None
    call_clause_text: str | None = None
    put_clause_text: str | None = None
    pure_bond_value: float | None = None
    valuation_date: str | None = None
    valuation_close: float | None = None
    pure_bond_premium_pct: float | None = None
    maturity_redemption_price: float | None = None
    call_trigger_price: float | None = None
    put_trigger_price: float | None = None
    quote_at: str | None = None
    outstanding_units: float | None = None
    outstanding_amount: float | None = None
    outstanding_observed_at: str | None = None
    outstanding_as_of: str | None = None
    outstanding_basis: str | None = None
    quantity_validation_price: float | None = None
    quantity_market_value: float | None = None
    stock_pb: float | None = None
    float_market_cap: float | None = None
    stock_metrics_quote_at: str | None = None
    cashflow_plan: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ConvertibleReferences(BaseModel):
    items: list[ConvertibleReference]
    fetched_at: str
    attempts: list[dict]
    warnings: list[str]


def _rows(payload, *, complete=False):
    data = payload.get('result') or {}
    rows = data.get('data')
    if payload.get('success') is not True or not isinstance(rows, list):
        raise ValueError('Invalid reference dataset')
    if complete and data.get('count') != len(rows):
        raise ValueError('Incomplete reference dataset')
    return rows


def _maturity(row, lifecycle, end):
    # A future EXPIRE_DATE can already have been changed for a pending early
    # redemption. Check the stated original integral term against VALUE_DATE;
    # use the source date only when coherent, never manufacture an anniversary.
    start = _date(row.get('VALUE_DATE'))
    years = number(row.get('BOND_EXPIRE'), positive=True)
    if lifecycle != 'listed' or not start or not end or years is None or not years.is_integer() or years > 10:
        return None
    start = date.fromisoformat(start)
    try:
        anniversary = start.replace(year=start.year + int(years))
    except ValueError:  # February 29: comparison only, not an invented payment date.
        anniversary = start.replace(year=start.year + int(years), day=28)
    return end if abs((date.fromisoformat(end) - anniversary).days) <= 7 else None


class ConvertibleReferenceProvider:
    def __init__(self, http=None):
        self.http = http or PublicHTTP()

    def fetch(self, symbols, today=None):
        symbols = sorted({normalize_symbol(s, kind='bond') for s in symbols})
        if not symbols or len(symbols) > 2000:
            raise ValueError('Invalid reference request')
        now = datetime.now(SH)
        today = today or now.date().isoformat()
        at = now.isoformat(timespec='seconds')
        found = {s: ConvertibleReference(code=s, fetched_at=at,
                 source_url=f'https://data.eastmoney.com/kzz/detail/{s[:6]}.html') for s in symbols}
        attempts = [{'provider': p, 'dataset': 'cb_terms_and_valuation', 'status': 'unsupported'}
                    for p in ('tickflow', 'fuyao')]
        warnings = ['公开纯债价值为供应商模型参考，折现曲线与净价/全价口径未披露，不是保本价格；不会替代手工试算。',
                    '条款、估值日期、报价日期分别展示；获取时间不是公告日。已退市债券的结束日不当作原合同到期日。']
        succeeded = False
        term_rows = {}
        # Bounded batches; no one-request-per-bond loop or authenticated scraping.
        for offset in range(0, len(symbols), 100):
            chunk = symbols[offset:offset + 100]
            codes = ','.join(f'"{s[:6]}"' for s in chunk)
            try:
                rows = _rows(self.http.get(URL, {'reportName': 'RPT_BOND_CB_LIST', 'columns': 'ALL',
                    'filter': f'(SECURITY_CODE in ({codes}))', 'pageSize': 100, 'pageNumber': 1,
                    'quoteColumns': QUOTE_COLUMNS, 'quoteType': '0'}).json(), complete=True)
                seen = set()
                for row in rows:
                    s = row.get('SECUCODE')
                    if s not in chunk or row.get('SECURITY_CODE') != s[:6] or s in seen:
                        raise ValueError('Reference identity mismatch')
                    seen.add(s)
                parsed = {}
                for row in rows:
                    s = row['SECUCODE']
                    if number(row.get('PAR_VALUE'), positive=True) != 100:
                        continue
                    end, listed, delisted = (_date(row.get(k)) for k in ('EXPIRE_DATE', 'LISTING_DATE', 'DELIST_DATE'))
                    life = ('terminated' if (delisted and delisted <= today) or (end and end <= today)
                            else 'not_yet_listed' if listed and listed > today else 'listed' if listed else 'unknown')
                    # EXPIRE_DATE has been observed rewritten on early redemption.
                    # Only currently listed, future dates are eligible references.
                    parsed[s] = dict(name=row.get('SECURITY_NAME_ABBR'), lifecycle=life,
                        maturity_date=_maturity(row, life, end), source_end_date=end,
                        listing_date=listed, conversion_end_date=_date(row.get('TRANSFER_END_DATE')),
                        conversion_start_date=_date(row.get('TRANSFER_START_DATE')),
                        stock_code=normalize_symbol(str(row['CONVERT_STOCK_CODE']), kind='stock') if row.get('CONVERT_STOCK_CODE') else None,
                        interest_start_date=_date(row.get('VALUE_DATE')), rating_agency=row.get('PARTY_NAME'),
                        credit_rating=row.get('RATING'), coupon_text=row.get('INTEREST_RATE_EXPLAIN'),
                        call_clause_text=row.get('REDEEM_CLAUSE'), put_clause_text=row.get('RESALE_CLAUSE'),
                        maturity_redemption_price=contract_redemption_price(row),
                        quote_at=_time(row.get('CB_STAMP')),
                        put_trigger_price=number(row.get('CB_PUT'), positive=True),
                        call_trigger_price=number(row.get('CB_CALL'), positive=True),
                        stock_pb=number(row.get('STOCK_PB')),
                        float_market_cap=number(row.get('STOCK_FLOAT_CAP'), positive=True),
                        stock_metrics_quote_at=_time(row.get('STOCK_STAMP')),
                        **_quantity_values(row.get('CB_UNITS'), row.get('CB_CAP'), row.get('CB_PRICE'), at))
                for s, values in parsed.items():
                    found[s] = found[s].model_copy(update=values)
                term_rows.update({row['SECUCODE']: row for row in rows if row['SECUCODE'] in parsed})
                attempts.append({'provider': PUBLIC, 'dataset': 'terms', 'status': 'success', 'rows': len(parsed)})
                succeeded |= bool(parsed)
            except Exception:  # noqa: BLE001 -- keep supplier errors private; independent valuation still useful
                attempts.append({'provider': PUBLIC, 'dataset': 'terms', 'status': 'failed'})
                warnings.append('部分到期日与条款本次读取失败，原始研究未改动，可重新读取。')
        # Latest available valuation day, then bounded batches at that date. This
        # avoids thousands of history rows and never labels fetch-day as value-day.
        try:
            base = {'type': 'RPTA_WEB_KZZ_LS', 'sty': 'ALL', 'st': 'date', 'sr': '-1', 'p': 1, 'source': 'WEB'}
            history_url = 'https://datacenter-web.eastmoney.com/api/data/get'
            latest = _rows(self.http.get(history_url, {**base, 'ps': 1}).json())
            day = _date(latest[0]['DATE']) if len(latest) == 1 else None
            if day is None or day > today or day < (date.fromisoformat(today) - timedelta(days=30)).isoformat():
                raise ValueError('Invalid valuation date')
            count = 0
            for offset in range(0, len(symbols), 100):
                chunk = symbols[offset:offset + 100]
                codes = ','.join(f'"{s[:6]}"' for s in chunk)
                rows = _rows(self.http.get(history_url, {**base, 'ps': 100,
                    'filter': f'(zcode in ({codes}))(date=\'{day}\')'}).json(), complete=True)
                values, seen = {}, set()
                for row in rows:
                    s = row.get('SECUCODE')
                    if s not in chunk or row.get('ZCODE') != s[:6] or _date(row.get('DATE')) != day or s in seen:
                        raise ValueError('Valuation identity/date mismatch')
                    seen.add(s)
                    value = number(row.get('PUREBONDVALUE'), positive=True)
                    if value is not None and found[s].lifecycle != 'terminated':
                        values[s] = dict(pure_bond_value=value, valuation_date=day,
                            valuation_close=number(row.get('FCLOSE'), positive=True),
                            pure_bond_premium_pct=number(row.get('PUREBONDOR')))
                for s, v in values.items():
                    found[s] = found[s].model_copy(update=v)
                count += len(values)
            attempts.append({'provider': PUBLIC, 'dataset': 'valuation', 'status': 'success' if count else 'empty', 'rows': count})
            succeeded |= bool(count)
            if day < (date.fromisoformat(today) - timedelta(days=7)).isoformat():
                warnings.append(f'估值数据较旧，截至 {day}；不冒充最新交易日数据。')
        except Exception:  # noqa: BLE001
            attempts.append({'provider': PUBLIC, 'dataset': 'valuation', 'status': 'failed'})
            warnings.append('本次未取得有效的带日期纯债估值，可继续查看条款及手工试算。')
        # Optional quote-derived trigger/maturity redemption amounts with own time.
        try:
            count = 0
            for offset in range(0, len(symbols), 100):
                chunk = symbols[offset:offset + 100]
                raw = self.http.get('https://push2.eastmoney.com/api/qt/ulist.np/get', {
                    'secids': ','.join(f'{1 if s.endswith(".SH") else 0}.{s[:6]}' for s in chunk),
                    'fltt': 2, 'invt': 2, 'fields': 'f2,f12,f13,f20,f21,f38,f39,f124,f239,f240,f241'}).json()
                rows = (raw.get('data') or {}).get('diff')
                if not isinstance(rows, list):
                    raise ValueError('Missing quote reference')
                seen, values = set(), {}
                for row in rows:
                    s = f'{row.get("f12")}.{"SH" if row.get("f13") == 1 else "SZ"}'
                    if s not in chunk or s in seen or row.get('f13') not in (0, 1):
                        raise ValueError('Quote identity mismatch')
                    seen.add(s)
                    if found[s].lifecycle == 'terminated':
                        continue
                    values[s] = dict(quote_at=quote_time(row.get('f124')),
                        put_trigger_price=number(row.get('f239'), positive=True) or found[s].put_trigger_price,
                        call_trigger_price=number(row.get('f240'), positive=True) or found[s].call_trigger_price,
                        maturity_redemption_price=number(row.get('f241'), positive=True) or found[s].maturity_redemption_price)
                    values[s].update(_quantity_values(row.get('f38'), row.get('f20'), row.get('f2'), at))
                for s, v in values.items():
                    found[s] = found[s].model_copy(update=v)
                count += len(values)
            attempts.append({'provider': PUBLIC, 'dataset': 'reference_prices', 'status': 'success', 'rows': count})
        except Exception:  # noqa: BLE001
            attempts.append({'provider': PUBLIC, 'dataset': 'reference_prices', 'status': 'failed'})
            warnings.append('直接报价参考入口暂不可用；保留已取得的数据中心字段和条款明确金额，不默认采用130%、70%或100元。')
        # Underlying metrics are a separate capability; never replace primary
        # prices or infer the stock binding from the bond's name/code.
        stocks = sorted({i.stock_code for i in found.values() if i.stock_code and (i.stock_pb is None or i.float_market_cap is None)})
        enriched = sum(i.stock_pb is not None and i.float_market_cap is not None for i in found.values())
        for p in ('tickflow', 'fuyao'):
            attempts.append({'provider': p, 'dataset': 'cb_underlying_reference_metrics', 'status': 'unsupported'})
        if enriched:
            attempts.append({'provider': PUBLIC, 'dataset': 'cb_underlying_metrics_datacenter', 'status': 'success', 'rows': enriched})
        if stocks:
            try:
                stock_values = {}
                for offset in range(0, len(stocks), 100):
                    chunk = stocks[offset:offset + 100]
                    raw = self.http.get('https://push2.eastmoney.com/api/qt/ulist.np/get', {
                        'secids': ','.join(f'{1 if s.endswith(".SH") else 0}.{s[:6]}' for s in chunk),
                        'fltt': 2, 'invt': 2, 'fields': 'f12,f13,f23,f21,f124'}).json()
                    rows = (raw.get('data') or {}).get('diff')
                    if not isinstance(rows, list):
                        raise ValueError('Missing stock reference metrics')
                    for row in rows:
                        s = f'{row.get("f12")}.{"SH" if row.get("f13") == 1 else "SZ"}'
                        if s not in chunk or s in stock_values or row.get('f13') not in (0, 1):
                            raise ValueError('Stock reference identity mismatch')
                        stock_values[s] = dict(stock_pb=number(row.get('f23')),
                            float_market_cap=number(row.get('f21'), positive=True),
                            stock_metrics_quote_at=quote_time(row.get('f124')))
                for item in found.values():
                    if item.stock_code in stock_values:
                        for key, value in stock_values[item.stock_code].items():
                            if value is not None:
                                setattr(item, key, value)
                attempts.append({'provider': PUBLIC, 'dataset': 'cb_underlying_reference_metrics',
                                 'status': 'success', 'rows': len(stock_values)})
            except Exception:  # noqa: BLE001 -- raw source errors never cross the boundary
                attempts.append({'provider': PUBLIC, 'dataset': 'cb_underlying_reference_metrics', 'status': 'failed'})
                warnings.append('部分正股PB与流通市值未取得；保留原行情，不用未知数代入占比。')
        for item in found.values():
            item.cashflow_plan = contract_cash_flows(term_rows.get(item.code, {}), item.maturity_date,
                item.maturity_redemption_price, item.lifecycle)
            if item.outstanding_amount is None:
                item.warnings.append('缺少通过单位一致性检查的存续张数，未将发行规模当作剩余规模。')
        if not succeeded:
            raise ConvertibleDataError(502, '公开条款与估值未返回有效资料，已保存的行情及研究不受影响，请重试')
        for item in found.values():
            if item.maturity_date is None:
                item.warnings.append('原合同到期日未确认；终止/退市日不能代替到期日。')
            if item.pure_bond_value is None:
                item.warnings.append('该债券在最新估值日没有有效纯债价值，未用面值代替。')
        return ConvertibleReferences(items=list(found.values()), fetched_at=at, attempts=attempts,
                                     warnings=list(dict.fromkeys(warnings)))


@lru_cache(maxsize=16)
def _cached(symbols, bucket):
    return ConvertibleReferenceProvider().fetch(symbols)


def references(codes):
    symbols = tuple(sorted({normalize_symbol(s, kind='bond') for s in codes}))
    if not symbols or len(symbols) > 2000:
        raise ConvertibleDataError(422, '须请求1至2000只明确的可转债代码')
    return _cached(symbols, int(time.monotonic() // 300)).model_copy(deep=True)
