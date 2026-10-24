from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import kline, stock_analysis
from app.data_providers import international as source
from app.data_providers.research_market import ResearchSourceError
from app.services import hk_stock_analysis
from app.services import international_stocks as service


def bars(symbol="AAPL.US"):
    return [
        dict(
            symbol=symbol,
            date=(date(2024, 1, 1) + timedelta(days=i)).isoformat(),
            open=100 + i,
            high=103 + i,
            low=99 + i,
            close=102 + i,
            volume=1000,
        )
        for i in range(80)
    ]


@pytest.mark.parametrize(
    "query,symbol",
    [
        ("AAPL", "AAPL.US"),
        ("苹果", "AAPL.US"),
        ("7203", "7203.JP"),
        ("7203.T", "7203.JP"),
        ("丰田", "7203.JP"),
        ("BRK.B", "BRK.B.US"),
    ],
)
def test_market_identity(query, symbol):
    assert source.normalize(query) == symbol
    assert source.is_international(symbol)
    assert not source.is_international("00700.HK")
    assert not source.is_international("600000.SH")


def test_priority_does_not_replace_good_primary():
    calls = []

    class Primary:
        name = "tickflow"

        def fetch(self, symbol):
            calls.append("primary")
            return bars()

    class Supplement:
        name = "public"

        def fetch(self, symbol):
            pytest.fail("must not replace good primary")

    result = source.fetch_daily("AAPL.US", [Primary(), Supplement()])
    assert result["source"] == "tickflow" and calls == ["primary"]


def test_failed_sources_traced_without_secrets():
    class Broken:
        name = "tickflow"

        def fetch(self, symbol):
            raise RuntimeError("SECRET")

    class Unsupported:
        name = "fuyao"

        def fetch(self, symbol):
            raise NotImplementedError

    class Good:
        name = "tickflow_public"

        def fetch(self, symbol):
            return bars()

    result = source.fetch_daily("AAPL.US", [Broken(), Unsupported(), Good()])
    assert [a["status"] for a in result["attempts"]] == ["failed", "unsupported", "success"]
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("kind", ["duplicate", "nan", "bad_high", "future", "short"])
def test_invalid_data_fails_closed(kind):
    data = bars()
    if kind == "duplicate":
        data.append(data[0])
    if kind == "nan":
        data[0]["close"] = float("nan")
    if kind == "bad_high":
        data[0]["high"] = 1
    if kind == "future":
        data[0]["date"] = "2999-01-01"
    if kind == "short":
        data = data[:20]
    with pytest.raises((ResearchSourceError, ValueError)):
        source.validate(data, "AAPL.US")


@pytest.mark.parametrize(
    "symbol,currency,zone",
    [("AAPL.US", "USD", "America/New_York"), ("7203.JP", "JPY", "Asia/Tokyo")],
)
def test_analysis_and_hot_path_isolation(monkeypatch, symbol, currency, zone):
    service._CACHE.clear()
    monkeypatch.setattr(
        source,
        "fetch_daily",
        lambda s: dict(
            rows=bars(s), source="tickflow" if currency == "USD" else "jquants", attempts=[]
        ),
    )
    value = service.snapshot(symbol)
    assert value["currency"] == currency and value["timezone"] == zone
    assert value["levels"]["sr"] == [] and value["close"] > 0
    assert value["quote"]["quote_status"] == "historical"
    assert value["rows"][0]["symbol"] == symbol
    monkeypatch.setattr(source, "fetch_daily", lambda s: pytest.fail("network on hot path"))
    assert service.cached_rows([symbol])[0]["close"] == value["close"]
    value["rows"][0]["close"] = 0
    assert service.snapshot(symbol)["rows"][0]["close"] > 0
    prompt = hk_stock_analysis.ai_messages(service.snapshot(symbol))
    assert currency in prompt[0]["content"] and "HKD" not in prompt[0]["content"]


@pytest.mark.parametrize("query,symbol", [("AAPL", "AAPL.US"), ("7203", "7203.JP")])
def test_search_routes_before_mainland(query, symbol):
    repo = SimpleNamespace(
        get_instruments_asset=lambda *a: pytest.fail("must not suggest mainland symbols")
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))
    result = kline.search_instruments(
        request, q=query, limit=10, asset_types="stock,index,hk,us,jp"
    )
    assert result["results"][0]["symbol"] == symbol


def test_japan_key_never_echoed(monkeypatch):
    from app import secrets_store

    saved = {}
    monkeypatch.setattr(secrets_store, "save", lambda d: saved.update(d))
    monkeypatch.setattr(
        secrets_store, "get_env_backed_secret", lambda *a: saved.get("jquants_api_key", "")
    )
    app = FastAPI()
    app.include_router(stock_analysis.router)
    with TestClient(app) as client:
        result = client.put(
            "/api/stock-analysis/japan-source", json={"api_key": "private-test-value"}
        )
        assert result.status_code == 200 and result.json()["configured"]
        assert "private-test-value" not in result.text


def test_japan_missing_key_does_not_make_up_rows(monkeypatch):
    from app import secrets_store

    monkeypatch.setattr(secrets_store, "get_env_backed_secret", lambda *a: "")
    monkeypatch.setattr(
        source.YahooDaily, "fetch", lambda *a: (_ for _ in ()).throw(NotImplementedError)
    )
    with pytest.raises(ResearchSourceError, match="日K"):
        source.fetch_daily("7203.JP")


@pytest.mark.parametrize("symbol,currency", [("AAPL.US", "USD"), ("7203.JP", "JPY")])
def test_international_ai_http_uses_same_snapshot(monkeypatch, symbol, currency):
    import json

    from app.services import ai_provider

    service._CACHE.clear()
    monkeypatch.setattr(
        source, "fetch_daily", lambda s: dict(rows=bars(s), source="tickflow", attempts=[])
    )
    captured = []

    async def model(messages, **kwargs):
        captured.extend(messages)
        yield "明确标记的测试模型输出"

    monkeypatch.setattr(ai_provider, "stream_ai_text", model)
    app = FastAPI()
    app.include_router(stock_analysis.router)
    with TestClient(app) as client:
        response = client.post("/api/stock-analysis/analyze", json={"symbol": symbol, "focus": ""})
        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert events[0]["type"] == "meta" and currency in events[0]["summary"]
        assert events[-1]["type"] == "done"
        assert captured and symbol in captured[1]["content"]
        assert "不复权" in captured[0]["content"]


def test_jquants_contract_with_labelled_fixture(monkeypatch):
    """Synthetic provider response, explicitly not authenticated live verification."""
    import httpx

    from app import secrets_store

    monkeypatch.setattr(secrets_store, "get_env_backed_secret", lambda *a: "synthetic-key")
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    dict(
                        Code="72030",
                        Date=r["date"],
                        O=r["open"],
                        H=r["high"],
                        L=r["low"],
                        C=r["close"],
                        Vo=r["volume"],
                    )
                    for r in bars("7203.JP")
                ]
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params, headers):
            calls.append((url, params.copy(), headers.copy()))
            return Response()

    monkeypatch.setattr(httpx, "Client", Client)
    result = source.JQuantsDaily().fetch("7203.JP")
    assert len(result) == 80 and result[0]["symbol"] == "7203.JP"
    assert calls[0][0] == "https://api.jquants.com/v2/equities/bars/daily"
    assert calls[0][1]["code"] == "7203" and calls[0][2] == {"x-api-key": "synthetic-key"}


def test_quote_permission_independent_from_daily_permission(monkeypatch):
    service._QUOTES.clear()
    service._CACHE.clear()
    monkeypatch.setattr(
        source,
        "paid_quote",
        lambda s: dict(
            symbol=s,
            name="Apple",
            asset_type="us",
            currency="USD",
            close=123,
            quote_status="source_timestamp",
            quote_at="2024-01-02",
            quote_warnings=[],
        ),
    )
    monkeypatch.setattr(
        service,
        "snapshot",
        lambda *a, **kw: pytest.fail("Daily failure must not hide valid quotes"),
    )
    data = service.quote_snapshot(["AAPL.US"])
    assert data["rows"][0]["close"] == 123 and data["rows"][0]["currency"] == "USD"
    service._QUOTES.clear()


@pytest.mark.parametrize("broken", [None, "currency", "symbol", "columns"])
def test_global_public_chart_contract(monkeypatch, broken):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.data_providers.research_market import PublicHTTP

    rows = bars("7203.JP")
    fields = {k: [r[k] for r in rows] for k in ("open", "high", "low", "close", "volume")}
    meta = dict(
        symbol="7203.T",
        currency="JPY",
        exchangeName="JPX",
        instrumentType="EQUITY",
        exchangeTimezoneName="Asia/Tokyo",
        regularMarketPrice=181,
        regularMarketTime=datetime(2024, 3, 20, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp(),
    )
    if broken == "currency":
        meta["currency"] = "USD"
    if broken == "symbol":
        meta["symbol"] = "6758.T"
    if broken == "columns":
        fields["close"] = fields["close"][:-1]
    payload = {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "timestamp": [
                        datetime.fromisoformat(r["date"])
                        .replace(tzinfo=ZoneInfo("Asia/Tokyo"))
                        .timestamp()
                        for r in rows
                    ],
                    "indicators": {"quote": [fields]},
                }
            ]
        }
    }

    class Response:
        def json(self):
            return payload

    monkeypatch.setattr(PublicHTTP, "get", lambda *a, **kw: Response())
    provider = source.YahooDaily()
    if broken:
        with pytest.raises(ResearchSourceError):
            provider.fetch("7203.JP")
    else:
        data = provider.fetch("7203.JP")
        assert len(data) == 80 and provider.metadata["currency"] == "JPY"
