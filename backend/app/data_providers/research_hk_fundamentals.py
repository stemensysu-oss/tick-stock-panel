"""Dated HK statements, independent of quote currency and mainland financial storage."""

from __future__ import annotations

import re
from datetime import date, datetime

from app.data_providers.research_market import SH, PublicHTTP, ResearchSourceError, number

TABLES = {"income": "利润表", "balance_sheet": "资产负债表", "cash_flow": "现金流量表"}
REPORTS = {
    "income": "RPT_HKF10_FN_INCOME_PC",
    "balance_sheet": "RPT_HKF10_FN_BALANCE_PC",
    "cash_flow": "RPT_HKF10_FN_CASHFLOW_PC",
}
CURRENCIES = {
    "人民币": "CNY",
    "港元": "HKD",
    "港币": "HKD",
    "美元": "USD",
    "CNY": "CNY",
    "RMB": "CNY",
    "HKD": "HKD",
    "USD": "USD",
}
PUBLIC_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def _day(value):
    if not value:
        return None
    result = date.fromisoformat(str(value)[:10])
    if result > datetime.now(SH).date() or result.year < 1990:
        raise ResearchSourceError("财报日期异常")
    return result.isoformat()


class TickflowFinancials:
    name = "tickflow"

    def fetch(self, symbol, table):
        from tickflow import TickFlow

        from app import secrets_store

        key = secrets_store.get_tickflow_key()
        if not key:
            raise PermissionError
        client = TickFlow(
            api_key=key,
            base_url=secrets_store.load().get("tickflow_base_url") or None,
            timeout=8,
            max_retries=0,
        )
        try:
            records = getattr(client.financials, table)([symbol], latest=False)
        finally:
            client.close()
        raw = records.get(symbol, [])
        reports = []
        for row in raw:
            # The SDK's mainland schema does not promise HK reporting currency/unit.
            # An account returning numbers alone is not sufficient evidence to label them HKD.
            currency = CURRENCIES.get(row.get("currency"))
            if not currency or row.get("amount_unit") not in ("元", "base_currency"):
                continue
            period = _day(row.get("period_end"))
            if not period:
                continue
            items = []
            for key, value in row.items():
                if key in {
                    "symbol",
                    "period_end",
                    "period_start",
                    "announce_date",
                    "currency",
                    "amount_unit",
                    "report_type",
                }:
                    continue
                if isinstance(value, (float, int)) and not isinstance(value, bool):
                    items.append(
                        dict(
                            code=key,
                            name=key,
                            value=number(value),
                            unit="currency_per_share" if "eps" in key else "base_currency",
                        )
                    )
            if items:
                reports.append(
                    dict(
                        period_end=period,
                        period_start=_day(row.get("period_start")),
                        announce_date=_day(row.get("announce_date")),
                        report_type=row.get("report_type") or "来源未提供",
                        currency=currency,
                        items=items,
                    )
                )
        return sorted(reports, key=lambda r: r["period_end"], reverse=True)[:4]


class FuyaoFinancials:
    name = "fuyao"

    def fetch(self, symbol, table):
        # The installed Fuyao financial contract is for A-shares; do not send HK
        # symbols to that endpoint or fabricate an HK endpoint.
        raise NotImplementedError


class EastmoneyFinancials:
    name = "eastmoney_public"

    def __init__(self, http=None):
        self.http = http or PublicHTTP()
        self.metadata = None

    def _get(self, report, symbol, **params):
        data = self.http.get(
            PUBLIC_URL,
            dict(
                reportName=report,
                columns="SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE",
                filter=f'(SECUCODE="{symbol}")',
                pageNumber=1,
                pageSize=500,
                source="F10",
                client="PC",
                **params,
            ),
        ).json()
        result = data.get("result") or {}
        if data.get("success") is not True or not isinstance(result.get("data"), list):
            raise ResearchSourceError("港股财报补充源响应异常")
        if int(result.get("pages") or 1) > 1:
            raise ResearchSourceError("港股财报超出本次完整分页上限，未采用截断报表")
        return result["data"]

    def _metadata(self, symbol):
        if self.metadata is not None:
            return self.metadata
        data = self._get("RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY", symbol)
        rows = data[0].get("REPORT_LIST", []) if data else []
        if not isinstance(rows, list):
            raise ResearchSourceError("港股财报目录异常")
        result = {}
        for row in rows:
            if row.get("SECUCODE") != symbol:
                raise ResearchSourceError("港股财报标的不一致")
            period = _day(row.get("REPORT_DATE"))
            currency = CURRENCIES.get(row.get("CURRENCY"))
            if period and currency:
                metadata = dict(
                    period_end=period,
                    period_start=_day(row.get("START_DATE")),
                    announce_date=None,
                    report_type=str(row.get("REPORT_TYPE") or "未知")[:24],
                    currency=currency,
                )
                if period in result and result[period] != metadata:
                    raise ResearchSourceError("同一报告期的币种或日期存在冲突")
                result[period] = metadata
        self.metadata = result
        return result

    def fetch(self, symbol, table):
        metadata = self._metadata(symbol)
        available = sorted(metadata, reverse=True)
        periods = available[:1]
        if available:
            latest = available[0]
            comparable = str(int(latest[:4]) - 1) + latest[4:]
            if comparable in metadata:
                periods.append(comparable)
        periods.extend(day for day in available if metadata[day]["report_type"] == "年报")
        periods = sorted(list(dict.fromkeys(periods))[:4], reverse=True)
        if not periods:
            return []
        dates = ",".join(f"'{day}'" for day in periods)
        # Dates originate from strict date parsing; the symbol is validated by fetch_financials.
        rows = self.http.get(
            PUBLIC_URL,
            dict(
                reportName=REPORTS[table],
                columns="ALL",
                filter=f'(SECUCODE="{symbol}")(REPORT_DATE in ({dates}))',
                pageNumber=1,
                pageSize=500,
                sortColumns="REPORT_DATE,STD_ITEM_CODE",
                sortTypes="-1,1",
                source="F10",
                client="PC",
            ),
        ).json()
        result = rows.get("result") or {}
        if rows.get("success") is not True or int(result.get("pages") or 1) > 1:
            raise ResearchSourceError("港股财报为空或报表被分页截断")
        raw = result.get("data")
        if not isinstance(raw, list) or len(raw) > 500:
            raise ResearchSourceError("港股财报行数异常")
        grouped, seen = {}, set()
        for row in raw:
            period = _day(row.get("REPORT_DATE"))
            if row.get("SECUCODE") != symbol or period not in periods:
                raise ResearchSourceError("港股财报标的或报告期不一致")
            code = str(row.get("STD_ITEM_CODE") or "")
            label = str(row.get("STD_ITEM_NAME") or "")
            if not re.fullmatch(r"\d{3,12}", code) or not label or len(label) > 100:
                raise ResearchSourceError("港股财报科目异常")
            identity = (period, code)
            if identity in seen:
                raise ResearchSourceError("港股财报科目重复")
            seen.add(identity)
            value = number(row.get("AMOUNT"))
            if value is None:
                continue
            grouped.setdefault(period, []).append(
                dict(
                    code=code,
                    name=label,
                    value=value,
                    unit="currency_per_share" if "每股" in label else "base_currency",
                )
            )
        return [
            {**metadata[period], "items": grouped[period]}
            for period in periods
            if grouped.get(period)
        ]


def fetch_financials(symbol, providers=None):
    if not re.fullmatch(r"\d{5}\.HK", str(symbol)):
        raise ValueError("请输入完整五位港股代码，如00700.HK")
    attempts, tables = [], {}
    providers = (
        providers
        if providers is not None
        else [TickflowFinancials(), FuyaoFinancials(), EastmoneyFinancials()]
    )
    for table, label in TABLES.items():
        tables[table] = dict(label=label, status="unavailable", reports=[])
        for provider in providers:
            try:
                reports = provider.fetch(symbol, table)
                if not reports:
                    status = "empty_or_unverified_currency"
                else:
                    tables[table].update(
                        status="available",
                        source=provider.name,
                        reports=reports,
                        source_url=(
                            f"https://emweb.securities.eastmoney.com/PC_HKF10/FinancialAnalysis/index?type=web&code={symbol[:5]}"
                            if provider.name == "eastmoney_public"
                            else "https://docs.tickflow.org/zh-Hans"
                        ),
                    )
                    attempts.append(
                        dict(
                            provider=provider.name,
                            dataset=table,
                            status="success",
                            reports=len(reports),
                        )
                    )
                    break
            except PermissionError:
                status = "unconfigured_or_denied"
            except NotImplementedError:
                status = "unsupported"
            except Exception:  # noqa: BLE001 -- supplier exception text may contain credentials
                status = "failed"
            attempts.append(dict(provider=provider.name, dataset=table, status=status))
    return dict(
        symbol=symbol,
        tables=tables,
        attempts=attempts,
        status="available"
        if all(t["reports"] for t in tables.values())
        else "partial"
        if any(t["reports"] for t in tables.values())
        else "unavailable",
        fetched_at=datetime.now(SH).isoformat(timespec="seconds"),
        valuation={},
        news=[],
        warnings=[
            "财报按来源列示币种计量，金额为该币种元，每股项目为元/股；不能与港元股价直接混算。",
            "利润与现金流为所列起止期间累计数，资产负债为期末余额；不可将中报直接当作全年或单季数。",
            "公开补充源未提供可靠披露日期，announce_date保持未知；这是抓取时可见的当前资料，不用于历史时点回测。",
            "公开财报整理可能延迟或重述，需对照公司原始报告；估值、每股分红和直接新闻未核验，不补造。",
        ],
        references=(
            [
                dict(
                    label="腾讯官方财务报告",
                    url="https://www.tencent.com/investors/financial-reports/",
                )
            ]
            if symbol == "00700.HK"
            else []
        ),
    )
