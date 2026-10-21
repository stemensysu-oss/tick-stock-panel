from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from tickflow import APIError

from app.services.convertibles_research import (
    ConvertibleConflictError,
    ConvertibleService,
)
from app.services.convertibles_sources import (
    ConvertibleDataError,
    ConvertibleQuote,
    ConvertibleQuoteBatch,
    ConvertibleQuoteService,
    TickFlowConvertibleProvider,
    normalize_symbol,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
FETCHED_AT = datetime(2026, 10, 21, 15, 1, tzinfo=SHANGHAI)
QUOTE_AT = datetime(2026, 10, 21, 15, 0, tzinfo=SHANGHAI)
TIMESTAMP = int(QUOTE_AT.timestamp() * 1000)
CSV = (
    "code,name,bond_price,stock_code,stock_price,conversion_price\n"
    "110001,测试转债,120,000001.SZ,12,10\n"
)


class StubClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows
        self.error = error
        self.calls = []
        self.closed = False
        self.quotes = SimpleNamespace(get=self.get)

    def get(self, *, symbols):
        self.calls.append(symbols)
        if self.error:
            raise self.error
        return self.rows

    def close(self):
        self.closed = True


def make_provider(rows=None, error=None, key="configured"):
    client = StubClient(rows=rows, error=error)
    provider = TickFlowConvertibleProvider(
        api_key_getter=lambda: key,
        client_factory=lambda _key: client,
        clock=lambda: FETCHED_AT,
    )
    return provider, client


def quote(symbol="110001.SH", **updates):
    row = {
        "symbol": symbol,
        "region": "CN",
        "last_price": 120.0,
        "prev_close": 100.0,
        "amount": 1_234_567.0,
        "timestamp": TIMESTAMP,
        "ext": {"change_pct": 0.2, "turnover_rate": 1.25},
    }
    return row | updates


def test_provider_batches_and_normalizes_percentage_points_yuan_and_time():
    provider, client = make_provider([quote(), quote("000001.SZ", last_price=12.0)])
    result = provider.quotes(["110001.SH", "000001.SZ", "110001.SH"])
    assert client.calls == [["000001.SZ", "110001.SH"]]
    assert client.closed
    assert result.fetched_at == FETCHED_AT.isoformat(timespec="seconds")
    bond = result.quotes["110001.SH"]
    assert bond.price == 120
    assert bond.change_pct == 20
    assert bond.turnover_rate_pct == 125
    assert bond.turnover_amount == 1_234_567
    assert bond.quote_at == QUOTE_AT.isoformat(timespec="seconds")


def test_missing_optional_values_are_null_and_zero_amount_is_not_missing():
    provider, _client = make_provider([quote(ext=None, amount=0, prev_close=None)])
    bond = provider.quotes(["110001.SH"]).quotes["110001.SH"]
    assert bond.change_pct is None
    assert bond.turnover_rate_pct is None
    assert bond.turnover_amount == 0


def test_change_can_be_derived_from_raw_prices_only_when_previous_close_positive():
    provider, _client = make_provider([quote(ext={}, last_price=90.0)])
    assert provider.quotes(["110001.SH"]).quotes["110001.SH"].change_pct == -10
    provider, _client = make_provider([quote(ext={}, prev_close=0)])
    assert provider.quotes(["110001.SH"]).quotes["110001.SH"].change_pct is None


@pytest.mark.parametrize("changes", [
    {"last_price": True},
    {"last_price": "nan"},
    {"last_price": -1},
    {"timestamp": TIMESTAMP // 1000},
    {"timestamp": None},
    {"timestamp": int(FETCHED_AT.timestamp() * 1000) + 601_000},
    {"region": "US"},
    {"ext": {"turnover_rate": -0.01}},
    {"amount": -1},
    {"ext": []},
])
def test_invalid_contract_fails_without_coercing_bad_data(changes):
    provider, client = make_provider([quote(**changes)])
    with pytest.raises(ConvertibleDataError) as exc:
        provider.quotes(["110001.SH"])
    assert exc.value.status_code == 502
    assert client.closed


def test_halted_zero_price_becomes_unknown_and_never_face_value_or_previous_close():
    provider, _client = make_provider([quote(last_price=0)])
    bond = provider.quotes(["110001.SH"]).quotes["110001.SH"]
    assert bond.price is None
    assert bond.change_pct is None


@pytest.mark.parametrize("rows", [
    {"data": []},
    [None],
    [quote(), quote()],
    [quote("600000.SH")],
])
def test_wrong_structure_duplicate_and_unrequested_symbols_are_rejected(rows):
    provider, _client = make_provider(rows)
    with pytest.raises(ConvertibleDataError):
        provider.quotes(["110001.SH"])


@pytest.mark.parametrize("upstream,expected", [(401, 403), (403, 403), (429, 429), (400, 422), (404, 404), (500, 502)])
def test_safe_source_errors_hide_upstream_details_and_release_client(upstream, expected):
    provider, client = make_provider(error=APIError(
        "private key and server body", code="PRIVATE_DETAILS", status_code=upstream,
        details={"secret": "never copy"},
    ))
    with pytest.raises(ConvertibleDataError) as exc:
        provider.quotes(["110001.SH"])
    assert exc.value.status_code == expected
    assert "private" not in str(exc.value)
    assert "secret" not in str(exc.value)
    assert client.closed


def test_missing_key_does_not_construct_or_call_client():
    provider, client = make_provider(key="")
    assert not provider.configured()
    with pytest.raises(ConvertibleDataError) as exc:
        provider.quotes(["110001.SH"])
    assert exc.value.status_code == 503
    assert client.calls == []


@pytest.mark.parametrize("code,kind,symbol", [
    ("110001", "bond", "110001.SH"),
    ("118001.sh", "bond", "118001.SH"),
    ("123001", "bond", "123001.SZ"),
    ("132001.SH", "bond", "132001.SH"),
    ("000001", "stock", "000001.SZ"),
    ("688001", "stock", "688001.SH"),
    ("920001.BJ", "stock", "920001.BJ"),
])
def test_market_suffix_is_normalized_for_explicit_asset_role(code, kind, symbol):
    assert normalize_symbol(code, kind=kind) == symbol


@pytest.mark.parametrize("code,kind", [
    ("000001.SH", "stock"),
    ("600000.SH", "bond"),
    ("110001.SZ", "bond"),
    ("999999", "bond"),
    ("../etc", "bond"),
    ("110001", "stock"),
])
def test_mismatched_market_and_unknown_security_role_are_rejected(code, kind):
    with pytest.raises(ConvertibleDataError) as exc:
        normalize_symbol(code, kind=kind)
    assert exc.value.status_code == 422


class StaticProvider:
    name = "test-provider"

    def __init__(self, quotes):
        self.rows = quotes
        self.calls = []

    def configured(self):
        return True

    def quotes(self, symbols):
        self.calls.append(symbols)
        return ConvertibleQuoteBatch(quotes=self.rows, fetched_at=FETCHED_AT.isoformat())


def normalized_quote(symbol, *, price=130.0, quote_at=None):
    return ConvertibleQuote(
        symbol=symbol, price=price, change_pct=3.0, turnover_amount=1000.0,
        turnover_rate_pct=2.0, quote_at=quote_at or QUOTE_AT.isoformat(),
    )


def test_refresh_merges_prices_only_and_clears_missing_stock_quote(tmp_path):
    store = ConvertibleService(tmp_path)
    old = store.import_csv(CSV, "2026-10-20", expected_revision="0")
    provider = StaticProvider({"110001.SH": normalized_quote("110001.SH")})
    saved = ConvertibleQuoteService(provider).refresh(store, expected_revision=old.revision)
    assert provider.calls == [["000001.SZ", "110001.SH"]]
    item = saved.items[0]
    assert item.code == "110001"
    assert item.bond_price == 130
    assert item.stock_price is None
    assert item.conversion_price == 10
    assert item.conversion_value is None
    assert item.turnover_amount == 1000
    assert item.quote_source == "test-provider"
    assert saved.as_of == "2026-10-21"
    assert store.snapshot() == saved


def test_empty_source_and_revision_conflict_preserve_old_snapshot(tmp_path):
    store = ConvertibleService(tmp_path)
    old = store.import_csv(CSV, "2026-10-20", expected_revision="0")
    provider = StaticProvider({})
    service = ConvertibleQuoteService(provider)
    with pytest.raises(ConvertibleDataError) as exc:
        service.refresh(store, expected_revision=old.revision)
    assert exc.value.status_code == 404
    assert store.snapshot() == old
    with pytest.raises(ConvertibleConflictError):
        service.refresh(store, expected_revision="0")
    assert len(provider.calls) == 1


def test_quote_time_never_moves_backwards(tmp_path):
    store = ConvertibleService(tmp_path)
    old = store.import_csv(CSV, "2026-10-20", expected_revision="0")
    current = ConvertibleQuoteService(StaticProvider({
        "110001.SH": normalized_quote("110001.SH"),
    })).refresh(store, expected_revision=old.revision)
    stale = ConvertibleQuoteService(StaticProvider({
        "110001.SH": normalized_quote("110001.SH", quote_at="2026-10-20T15:00:00+08:00"),
    }))
    with pytest.raises(ConvertibleDataError) as exc:
        stale.refresh(store, expected_revision=current.revision)
    assert exc.value.status_code == 502
    assert store.snapshot() == current


def test_user_edit_during_network_request_wins_without_stale_quote_overwrite(tmp_path):
    store = ConvertibleService(tmp_path)
    old = store.import_csv(CSV, "2026-10-20", expected_revision="0")

    class UpdatingProvider(StaticProvider):
        def quotes(self, symbols):
            self.new_snapshot = store.import_csv(
                CSV.replace("测试转债", "用户新清单"), "2026-10-21",
                expected_revision=old.revision,
            )
            return super().quotes(symbols)

    provider = UpdatingProvider({"110001.SH": normalized_quote("110001.SH")})
    with pytest.raises(ConvertibleConflictError):
        ConvertibleQuoteService(provider).refresh(store, expected_revision=old.revision)
    assert store.snapshot() == provider.new_snapshot


def test_quote_batch_older_than_import_date_fails_safely(tmp_path):
    store = ConvertibleService(tmp_path)
    old = store.import_csv(CSV, "2026-10-22", expected_revision="0")
    service = ConvertibleQuoteService(StaticProvider({
        "110001.SH": normalized_quote("110001.SH"),
    }))
    with pytest.raises(ConvertibleDataError) as exc:
        service.refresh(store, expected_revision=old.revision)
    assert exc.value.status_code == 502
    assert store.snapshot() == old
