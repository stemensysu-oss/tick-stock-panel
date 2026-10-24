import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data_providers import research_hk_fundamentals as source
from app.data_providers.research_market import ResearchSourceError
from app.services import hk_fundamentals as service


def fake_http(*, currency="人民币", wrong_symbol=False, duplicate=False, pages=1):
    class HTTP:
        def get(self, url, params):
            symbol = "00005.HK" if wrong_symbol else "00700.HK"
            if "SUMMARY" in params["reportName"]:
                rows = [
                    {
                        "REPORT_LIST": [
                            dict(
                                SECUCODE=symbol,
                                REPORT_DATE="2026-06-30",
                                START_DATE="2026-01-01",
                                CURRENCY=currency,
                                REPORT_TYPE="中报",
                            )
                        ]
                    }
                ]
            else:
                rows = [
                    dict(
                        SECUCODE=symbol,
                        REPORT_DATE="2026-06-30",
                        STD_ITEM_CODE="004001999",
                        STD_ITEM_NAME="营运收入",
                        AMOUNT=401243000000,
                    ),
                    dict(
                        SECUCODE=symbol,
                        REPORT_DATE="2026-06-30",
                        STD_ITEM_CODE="004027002",
                        STD_ITEM_NAME="每股基本盈利",
                        AMOUNT=12.639,
                    ),
                    dict(
                        SECUCODE=symbol,
                        REPORT_DATE="2026-06-30",
                        STD_ITEM_CODE="004030001",
                        STD_ITEM_NAME="股本",
                        AMOUNT=None,
                    ),
                ]
                if duplicate:
                    rows.append(rows[0])
            return SimpleNamespace(
                json=lambda: dict(success=True, result=dict(data=rows, pages=pages))
            )

    return HTTP()


def test_currency_is_from_report_metadata_not_hk_quote_or_indicator():
    rows = source.EastmoneyFinancials(fake_http()).fetch("00700.HK", "income")
    assert rows[0]["currency"] == "CNY"
    assert rows[0]["period_start"] == "2026-01-01" and rows[0]["announce_date"] is None
    assert rows[0]["items"][0]["value"] == 401243000000
    assert rows[0]["items"][1]["value"] == 12.639
    assert rows[0]["items"][1]["unit"] == "currency_per_share"
    assert len(rows[0]["items"]) == 2  # missing share capital is not zero


@pytest.mark.parametrize("kwargs", [{"wrong_symbol": True}, {"duplicate": True}, {"pages": 2}])
def test_mixed_symbol_duplicate_and_truncated_reports_are_rejected(kwargs):
    with pytest.raises(ResearchSourceError):
        source.EastmoneyFinancials(fake_http(**kwargs)).fetch("00700.HK", "income")


def test_unknown_currency_never_inferred_from_exchange():
    assert (
        source.EastmoneyFinancials(fake_http(currency="未说明")).fetch("00700.HK", "income") == []
    )


def test_source_priority_is_per_statement_and_secrets_are_not_returned():
    reports = source.EastmoneyFinancials(fake_http()).fetch("00700.HK", "income")
    calls = []

    class Primary:
        name = "tickflow"

        def fetch(self, symbol, table):
            calls.append((self.name, table))
            if table == "income":
                return reports
            raise ValueError("private-token-must-not-appear")

    class Secondary:
        name = "fuyao"

        def fetch(self, symbol, table):
            calls.append((self.name, table))
            raise NotImplementedError

    class Public:
        name = "eastmoney_public"

        def fetch(self, symbol, table):
            calls.append((self.name, table))
            return reports

    result = source.fetch_financials("00700.HK", [Primary(), Secondary(), Public()])
    assert result["status"] == "available"
    assert ("eastmoney_public", "income") not in calls and ("fuyao", "income") not in calls
    assert calls[-3:] == [
        ("tickflow", "cash_flow"),
        ("fuyao", "cash_flow"),
        ("eastmoney_public", "cash_flow"),
    ]
    assert (
        "private-token" not in json.dumps(result)
        and result["valuation"] == {}
        and result["news"] == []
    )


def test_current_financials_reach_real_http_ai_input_without_changing_price_currency(monkeypatch):
    from app.api import stock_analysis as api
    from app.services import ai_provider
    from app.services import hk_stock_analysis as hk

    result = source.fetch_financials("00700.HK", [source.EastmoneyFinancials(fake_http())])
    monkeypatch.setattr(service, "snapshot", lambda *a, **kw: deepcopy(result))
    monkeypatch.setattr(
        hk,
        "snapshot",
        lambda *a: dict(
            symbol="00700.HK",
            name="腾讯控股",
            asset_type="hk",
            currency="HKD",
            price_basis="unadjusted",
            volume_unit="source_native",
            close=386,
            as_of="2026-10-23",
            source_name="TickFlow",
            fetched_at="test",
            warnings=[],
            levels={},
            rows=[dict(date="2026-10-23", close=386)],
        ),
    )
    received = []

    async def model(messages, **kwargs):
        received.extend(messages)
        yield "【测试模型】收入401243000000 CNY，期间2026-01-01至2026-06-30。"

    monkeypatch.setattr(ai_provider, "stream_ai_text", model)
    app = FastAPI()
    app.include_router(api.router)
    app.state.repo = SimpleNamespace()
    with TestClient(app) as client:
        financials = client.get("/api/stock-analysis/hk-fundamentals?symbol=00700.HK").json()
        assert financials["tables"]["income"]["reports"][0]["currency"] == "CNY"
        response = client.post(
            "/api/stock-analysis/analyze", json={"symbol": "00700.HK", "focus": "财务报表"}
        )
    assert '"type": "done"' in response.text
    payload = json.loads(received[1]["content"].split("\n")[0])
    assert payload["currency"] == "HKD"
    assert (
        payload["fundamentals"]["tables"]["income"]["reports"][0]["items"][0]["value"]
        == 401243000000
    )
    assert "财务、基本面与直接新闻均缺失" not in received[0]["content"]
    assert "禁止直接相除" in received[0]["content"]


def test_refresh_failure_keeps_original_good_reports_and_fetch_time(monkeypatch):
    service._CACHE.clear()
    monkeypatch.setattr(service.secrets_store, "get_tickflow_key", lambda: "")
    monkeypatch.setattr(service.secrets_store, "load", lambda: {})
    good = source.fetch_financials("00700.HK", [source.EastmoneyFinancials(fake_http())])
    monkeypatch.setattr(service, "fetch_financials", lambda *a: deepcopy(good))
    first = service.snapshot("00700.HK")
    monkeypatch.setattr(
        service, "fetch_financials", lambda *a: source.fetch_financials("00700.HK", [])
    )
    stale = service.snapshot("00700.HK", force=True)
    assert stale["status"] == "stale" and stale["fetched_at"] == first["fetched_at"]
    assert stale["tables"] == first["tables"]
    service._CACHE.clear()


def test_invalid_symbols_do_not_call_financial_sources():
    with pytest.raises(ValueError):
        source.fetch_financials('00700.HK")(other="1')
