from datetime import date, timedelta
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import stock_analysis as api
from app.data_providers import research_hk_daily as daily
from app.data_providers.research_market import ResearchSourceError
from app.services import ai_provider
from app.services import hk_stock_analysis as hk


def bars(count=80):
    start = date(2024, 1, 1)
    return [
        dict(
            symbol="00700.HK",
            date=(start + timedelta(days=i)).isoformat(),
            open=100 + i,
            high=102 + i,
            low=99 + i,
            close=101 + i,
            volume=1000 + i,
        )
        for i in range(count)
    ]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    hk._CACHE.clear()
    monkeypatch.setattr(
        hk,
        "quote_snapshot",
        lambda *a, **k: {
            "rows": [
                dict(
                    symbol="00700.HK",
                    name="腾讯控股",
                    currency="HKD",
                    close=200,
                    quote_at="2024-04-01T16:00:00+08:00",
                    quote_source="test",
                )
            ]
        },
    )
    monkeypatch.setattr(
        hk, "fetch_daily", lambda *a: dict(rows=bars(), source="tencent_public", attempts=[])
    )
    yield
    hk._CACHE.clear()


@pytest.mark.parametrize(
    "changes", [{"close": -1}, {"high": 0}, {"low": 999}, {"volume": -1}, {"open": float("nan")}]
)
def test_invalid_ohlcv_is_rejected(changes):
    rows = bars()
    rows[-1].update(changes)
    with pytest.raises(ResearchSourceError):
        daily.validate_bars(rows, "00700.HK")


def test_duplicate_and_future_date_rejected():
    for day in ["2024-01-01", "2999-01-01"]:
        rows = bars()
        rows[-1]["date"] = day
        with pytest.raises(ResearchSourceError):
            daily.validate_bars(rows, "00700.HK")


def test_today_excluded_and_short_sample_rejected():
    rows = bars()
    rows.append({**rows[-1], "date": date.today().isoformat()})
    assert len(daily.validate_bars(rows, "00700.HK")) == 80
    with pytest.raises(ResearchSourceError):
        daily.validate_bars(bars(20), "00700.HK")


def test_priority_success_does_not_call_supplement():
    class Primary:
        name = "tickflow"

        def fetch(self, *a):
            return bars()

    class Other:
        name = "public"

        def fetch(self, *a):
            pytest.fail("primary succeeded")

    result = daily.fetch_daily("00700.HK", providers=[Primary(), Other()])
    assert result["source"] == "tickflow" and len(result["attempts"]) == 1


def test_fallback_records_unconfigured_and_unsupported():
    class Primary:
        name = "tickflow"

        def fetch(self, *a):
            raise PermissionError

    class Secondary:
        name = "fuyao"

        def fetch(self, *a):
            raise NotImplementedError

    class Public:
        name = "tencent_public"

        def fetch(self, *a):
            return bars()

    result = daily.fetch_daily("00700.HK", providers=[Primary(), Secondary(), Public()])
    assert [a["status"] for a in result["attempts"]] == ["unconfigured", "unsupported", "success"]


def test_snapshot_units_indicators_levels_and_copy(monkeypatch):
    result = hk.snapshot("00700.HK")
    assert result["currency"] == "HKD" and result["price_basis"] == "unadjusted"
    assert result["as_of"] == bars()[-1]["date"]
    assert result["levels"]["pivot"] and result["levels"]["sr"] == []
    assert result["rows"][-1]["ma20"] == pytest.approx(sum(range(161, 181)) / 20)
    assert result["rows"][-1]["rsi_14"] is not None
    assert "limit_up_price" not in result["rows"][-1]
    result["rows"][-1]["close"] = 0
    monkeypatch.setattr(hk, "fetch_daily", lambda *a: pytest.fail("cache must be shared"))
    assert hk.snapshot("00700.HK")["close"] == 180


def test_currency_unknown_not_relabelled(monkeypatch):
    monkeypatch.setattr(
        hk, "quote_snapshot", lambda *a, **k: {"rows": [dict(symbol="00700.HK", currency="CNY")]}
    )
    with pytest.raises(ResearchSourceError):
        hk.snapshot("00700.HK")


def test_force_failure_preserves_cached_data(monkeypatch):
    hk.snapshot("00700.HK")
    monkeypatch.setattr(
        hk, "fetch_daily", lambda *a: (_ for _ in ()).throw(ResearchSourceError("offline"))
    )
    with pytest.raises(ResearchSourceError):
        hk.snapshot("00700.HK", force=True)
    assert hk.snapshot("00700.HK")["close"] == 180


def test_tickflow_compact_contract_and_close(monkeypatch):
    import tickflow

    from app import secrets_store

    calls = []

    class Client:
        def __init__(self, **kw):
            self.klines = self

        def get(self, symbol, **kw):
            calls.append((symbol, kw))
            rows = bars()
            return {
                **{k: [r[k] for r in rows] for k in ("open", "close", "high", "low", "volume")},
                "timestamp": [1704067200000 + i * 86400000 for i in range(len(rows))],
            }

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(tickflow, "TickFlow", Client)
    monkeypatch.setattr(secrets_store, "get_tickflow_key", lambda: "fake")
    monkeypatch.setattr(secrets_store, "load", lambda: {})
    assert len(daily.TickflowHkDaily().fetch("00700.HK", 320)) == 80
    assert calls[0][1] == {"period": "1d", "count": 320, "adjust": "none"} and calls[-1] == "closed"


def test_public_raw_contract_does_not_accept_qfq_as_raw(monkeypatch):
    values = [[r["date"], r["open"], r["close"], r["high"], r["low"], r["volume"]] for r in bars()]

    class HTTP:
        def get(self, url, params):
            return SimpleNamespace(json=lambda: {"code": 0, "data": {"hk00700": {"day": values}}})

    monkeypatch.setattr(daily, "PublicHTTP", HTTP)
    assert daily.TencentHkDaily().fetch("00700.HK", 320)[-1]["close"] == 180
    monkeypatch.setattr(
        HTTP,
        "get",
        lambda *a: SimpleNamespace(
            json=lambda: {"code": 0, "data": {"hk00700": {"qfqday": values}}}
        ),
    )
    with pytest.raises(ResearchSourceError):
        daily.TencentHkDaily().fetch("00700.HK", 320)


def test_http_data_levels_ai_stream_full_path(monkeypatch, tmp_path):
    monkeypatch.setattr(api.stock_reports._store, "_path", lambda: tmp_path / "reports.json")
    received = []

    async def model(messages, **kw):
        received.extend(messages)
        yield "【测试模型】腾讯的历史收盘为180港元。"

    monkeypatch.setattr(ai_provider, "stream_ai_text", model)
    app = FastAPI()
    app.include_router(api.router)
    app.state.repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        resolve_asset_type=lambda *a: pytest.fail("HK must not use A-share repo"),
    )
    with TestClient(app) as client:
        data = client.get("/api/stock-analysis/hk-data?symbol=00700.HK").json()
        assert data["levels"]["pivot"]
        assert (
            client.get("/api/stock-analysis/levels?symbol=00700.HK").json()["as_of"]
            == data["as_of"]
        )
        response = client.post(
            "/api/stock-analysis/analyze", json={"symbol": "00700.HK", "focus": ""}
        )
        import json

        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert [r["type"] for r in events] == ["meta", "delta", "done"]
        assert "HKD" in events[0]["summary"]
        text = "\n".join(r["content"] for r in received)
        assert "00700.HK" in text and "2024-03-20" in text and "180" in text
        assert "不得套用A股" in text and "财务" in text and "直接新闻" in text
        saved = client.post(
            "/api/stock-analysis/reports",
            json={
                "symbol": "00700.HK",
                "name": "腾讯控股",
                "content": events[1]["content"],
                "summary": events[0]["summary"],
                "close": events[0]["close"],
                "levels": events[0]["levels"],
            },
        ).json()["report"]
        assert client.get("/api/stock-analysis/reports").json()["reports"][0]["id"] == saved["id"]
        assert "测试模型" in saved["content"]
        assert client.get("/api/stock-analysis/hk-data?symbol=600000.SH").status_code == 422


def test_model_error_redacted_and_no_fake_success(monkeypatch):
    async def model(*a, **kw):
        raise ValueError("secret-token-do-not-leak")
        yield ""

    monkeypatch.setattr(ai_provider, "stream_ai_text", model)

    async def run():
        return [r async for r in hk.analyze_stream("00700.HK")]

    import json

    events = [json.loads(r) for r in anyio.run(run)]
    assert events[-1]["type"] == "error" and not any(r["type"] == "done" for r in events)
    assert "secret-token" not in str(events)
