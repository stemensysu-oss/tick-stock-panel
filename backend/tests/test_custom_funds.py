"""Fund extension contract: documented requests, units, empty and failure paths."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom import funds
from app.custom.funds.provider import FuyaoFundClient, FuyaoFundProvider
from app.custom.funds.service import FundDataError, FundResearchService
from app.extensions.loader import configure_backend_extensions


def _ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)


def _provider(payload: object, status: int = 200):
    requests: list[httpx.Request] = []
    clients: list[FuyaoFundClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)

    def factory(api_key: str) -> FuyaoFundClient:
        client = FuyaoFundClient(api_key)
        client._http.close()
        client._http = httpx.Client(
            base_url="https://fuyao.aicubes.cn",
            headers={"X-api-key": api_key},
            transport=httpx.MockTransport(handler),
        )
        clients.append(client)
        return client

    return FuyaoFundProvider("test-only-key", client_factory=factory), requests, clients


def _client(monkeypatch: pytest.MonkeyPatch, provider: FuyaoFundProvider) -> TestClient:
    monkeypatch.setattr("app.extensions.loader._custom_module_names", lambda: [funds.__name__])
    app = FastAPI()
    registry, errors = configure_backend_extensions(app)
    assert not errors
    assert "stemensysu.funds" in registry.extension_ids()
    app.dependency_overrides[funds.get_service] = lambda: FundResearchService(provider)
    return TestClient(app)


def test_profile_uses_documented_endpoint_and_beijing_date() -> None:
    provider, requests, clients = _provider({"code": 0, "data": {
        "timestamp": _ms("2026-07-01"),
        "item": [{"thscode": "025480.OF", "fund_name": "测试基金", "mgmt_name": "管理人",
                  "manager_name": None, "estab_date": _ms("2025-12-30"), "unit_nav": 1.2345}],
    }})
    result = FundResearchService(provider).profile("025480.OF")
    assert result.profile is not None
    assert result.profile.established_date == "2025-12-30"
    assert result.profile.unit_nav == 1.2345
    assert result.profile.manager_name is None
    assert requests[0].url.path == "/api/fund/profile/detail"
    assert dict(requests[0].url.params) == {"thscode": "025480.OF"}
    assert requests[0].headers["X-api-key"] == "test-only-key"
    assert clients[0]._http.is_closed


def test_nav_preserves_adjusted_vs_unit_values_and_sorts_dates() -> None:
    provider, requests, _ = _provider({"code": 0, "data": {"timestamp": 0, "item": [
        {"nav_date": _ms("2026-07-02"), "unit_nav": 1.02, "adj_nav": 2.04},
        {"nav_date": _ms("2026-07-01"), "unit_nav": 1.0, "adj_nav": None},
    ]}})
    result = FundResearchService(provider).nav("510300.SH", "year")
    assert result.timestamp_ms is None
    assert [item.date for item in result.items] == ["2026-07-01", "2026-07-02"]
    assert result.items[0].adj_nav is None
    assert result.items[1].unit_nav == 1.02
    assert result.items[1].adj_nav == 2.04
    assert requests[0].url.path == "/api/fund/performance/nav"
    assert dict(requests[0].url.params) == {
        "thscode": "510300.SH", "range": "year", "nav_type": "unit,adj",
    }


def test_holdings_preserves_small_percent_and_disclosure_dates() -> None:
    provider, requests, _ = _provider({"code": 0, "data": {
        "timestamp": 0, "total_stock_ratio_pct": 82.3, "total_bond_ratio_pct": 0,
        "item": [{"thscode": "300750.SZ", "stock_name": "测试资产", "hold_ratio": 0.12,
                  "asset_type": "stock", "end_date_ms": _ms("2026-06-30"),
                  "publish_date_ms": _ms("2026-07-20")}],
    }})
    result = FundResearchService(provider).holdings("025480.OF")
    assert result.items[0].weight_pct == 0.12  # 0.12%, never inferred to be 12%.
    assert result.items[0].report_date == "2026-06-30"
    assert result.items[0].publish_date == "2026-07-20"
    assert result.stock_ratio_pct == 82.3
    assert result.bond_ratio_pct == 0
    assert result.fund_ratio_pct is None
    assert requests[0].url.path == "/api/fund/portfolio/holdings"


@pytest.mark.parametrize("payload", [{"code": 0, "data": {"item": []}}, {"code": 3002, "message": "not ready"}])
def test_empty_data_is_explicit(payload: dict) -> None:
    provider, _, _ = _provider(payload)
    service = FundResearchService(provider)
    assert service.profile("025480.OF").profile is None
    assert service.nav("025480.OF", "month").items == []
    assert service.holdings("025480.OF").items == []


@pytest.mark.parametrize("ticker", ["510300", "600000", "510300.US", "../settings", "510300.SH,025480.OF"])
def test_requires_explicit_supported_fund_suffix(ticker: str) -> None:
    provider, requests, _ = _provider({"code": 0, "data": {"item": []}})
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile(ticker)
    assert error.value.status_code == 422
    assert requests == []


def test_invalid_range_does_not_request_source() -> None:
    provider, requests, _ = _provider({"code": 0, "data": {"item": []}})
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).nav("510300.SH", "decade")
    assert error.value.status_code == 422
    assert requests == []


@pytest.mark.parametrize(("code", "status"), [(2001, 403), (2002, 403), (2003, 403), (3001, 404), (3004, 422), (4001, 429), (9999, 502)])
def test_business_failures_are_sanitized_and_close_client(code: int, status: int) -> None:
    provider, _, clients = _provider({"code": code, "message": "sensitive test-only-key"})
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile("025480.OF")
    assert error.value.status_code == status
    assert "sensitive" not in str(error.value)
    assert "test-only-key" not in str(error.value)
    assert clients[0]._http.is_closed


@pytest.mark.parametrize(("http_status", "expected"), [(401, 403), (403, 403), (429, 429), (500, 502)])
def test_http_failures(http_status: int, expected: int) -> None:
    provider, _, _ = _provider({}, status=http_status)
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile("025480.OF")
    assert error.value.status_code == expected


@pytest.mark.parametrize("data", [
    {},
    {"item": "bad"}, {"item": ["bad"]},
    {"item": [{"nav_date": _ms("2026-07-01"), "unit_nav": "NaN"}]},
    {"item": [{"nav_date": None, "unit_nav": 1.2}]},
    {"item": [{"nav_date": _ms("2026-07-01"), "unit_nav": -1}]},
    {"item": [{"nav_date": _ms("2026-07-01"), "unit_nav": True}]},
    {"item": [{"nav_date": _ms("2026-07-01")}, {"nav_date": _ms("2026-07-01")}]},
])
def test_malformed_nav_fails_closed(data: dict) -> None:
    provider, _, _ = _provider({"code": 0, "data": data})
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).nav("025480.OF", "year")
    assert error.value.status_code == 502


def test_wrong_fund_profile_is_rejected() -> None:
    provider, _, _ = _provider({"code": 0, "data": {"item": [{"thscode": "510300.SH"}]}})
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile("025480.OF")
    assert error.value.status_code == 502


@pytest.mark.parametrize("payload", [[], None, "bad", {"code": 0, "data": [1]}])
def test_malformed_response_envelope_is_safe(payload: object) -> None:
    provider, _, clients = _provider(payload)
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile("025480.OF")
    assert error.value.status_code == 502
    assert clients[0]._http.is_closed


def test_timeout_is_sanitized_and_client_closed() -> None:
    provider, _, clients = _provider(httpx.ReadTimeout("sensitive test-only-key"))
    with pytest.raises(FundDataError) as error:
        FundResearchService(provider).profile("025480.OF")
    assert error.value.status_code == 502
    assert "sensitive" not in str(error.value)
    assert clients[0]._http.is_closed


def test_configured_status_never_exposes_key_or_claims_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(funds, "get_api_key", lambda: "test-only-key")
    response = funds.status()
    assert response.configured is True
    assert response.permission_status == "unverified"
    assert "test-only-key" not in response.model_dump_json()


def test_extension_loads_without_key_and_api_reports_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(funds, "get_api_key", lambda: "")
    client = _client(monkeypatch, FuyaoFundProvider(""))
    response = client.get("/api/ext/funds/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["permission_status"] == "unverified"
    assert "FUYAO_API_KEY" in response.json()["message"]
    for endpoint in ["profile", "nav", "holdings"]:
        response = client.get(f"/api/ext/funds/025480.OF/{endpoint}")
        assert response.status_code == 503
        assert "API Key" in response.json()["detail"]
        assert "FUYAO_API_KEY" in response.json()["detail"]


def test_api_success_empty_validation_and_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, _, _ = _provider({"code": 0, "data": {"item": []}})
    client = _client(monkeypatch, provider)
    assert client.get("/api/ext/funds/025480.OF/profile").json()["profile"] is None
    assert client.get("/api/ext/funds/025480.OF/nav?range=month").json() == {
        "ticker": "025480.OF", "provider": "fuyao", "timestamp_ms": None,
        "range": "month", "items": [],
    }
    assert client.get("/api/ext/funds/510300/nav").status_code == 422
    assert client.get("/api/ext/funds/510300.SH/nav?range=decade").status_code == 422
    denied, _, _ = _provider({"code": 2003, "message": "sensitive test-only-key"})
    client = _client(monkeypatch, denied)
    response = client.get("/api/ext/funds/025480.OF/holdings")
    assert response.status_code == 403
    assert "sensitive" not in response.text
