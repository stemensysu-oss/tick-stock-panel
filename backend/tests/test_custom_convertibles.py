from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom import convertibles
from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.services.convertibles_research import (
    MAX_CSV_BYTES,
    MAX_ROWS,
    ConvertibleConflictError,
    ConvertibleImportError,
    ConvertibleService,
    ConvertibleStoreError,
    parse_csv,
)
from app.services.convertibles_sources import (
    ConvertibleQuote,
    ConvertibleQuoteBatch,
    ConvertibleQuoteService,
    TickFlowConvertibleProvider,
)

CSV = (
    "code,name,bond_price,stock_code,stock_price,conversion_price,face_value,maturity_date\n"
    "110001,测试转债,120,000001.SZ,12,10,100,2030-01-01\n"
)
AS_OF = "2026-10-21"


def test_metrics_use_unadjusted_yuan_prices_and_percentage_points():
    preview = parse_csv(CSV, AS_OF)
    item = preview.items[0]
    assert preview.valid
    assert item.stock_code == "000001.SZ"
    assert item.conversion_value == 120
    assert item.conversion_premium_pct == 0
    assert item.double_low == 120

    premium = parse_csv(CSV.replace(",120,000001", ",144,000001"), AS_OF).items[0]
    assert premium.conversion_premium_pct == 20
    assert premium.double_low == 164


def test_nonstandard_face_value_is_rejected_to_keep_double_low_comparable():
    text = CSV.replace(",120,000001", ",240,000001").replace(",100,2030", ",200,2030")
    result = parse_csv(text, AS_OF)
    assert not result.valid
    assert result.items == []
    assert result.errors[0].field == "face_value"
    assert "仅支持每张面值 100 元" in result.errors[0].message


def test_bom_chinese_aliases_missing_values_and_default_face_value():
    preview = parse_csv(
        "\ufeff转债代码,转债名称,现价,正股代码,正股价,转股价,到期日期,强赎状态\n"
        "110002,测试乙债,90,000002.SZ,8,10,2030-02-01,未提供公告依据\n"
        "110003,测试丙债,,,,,,\n",
        AS_OF,
    )
    assert preview.valid
    assert preview.warnings
    first, missing = preview.items
    assert first.face_value == 100
    assert first.conversion_value == 80
    assert first.conversion_premium_pct == 12.5
    assert first.double_low == 102.5
    assert first.redemption_status == "未提供公告依据"
    assert missing.bond_price is None
    assert missing.stock_price is None
    assert missing.conversion_value is None
    assert missing.conversion_premium_pct is None
    assert missing.double_low is None
    assert missing.maturity_date is None


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "1e999", "1e-999", "110%"])
def test_invalid_prices_do_not_produce_financial_results(value):
    preview = parse_csv(CSV.replace(",120,000001", f",{value},000001"), AS_OF)
    assert not preview.valid
    assert preview.errors[0].row == 2
    assert preview.errors[0].field == "bond_price"
    assert preview.items == []


def test_duplicate_codes_reject_the_entire_import_and_preserve_previous_snapshot(tmp_path):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, AS_OF, expected_revision="0")
    duplicate = CSV + "110001.SH,重复转债,130,000001.SZ,12,10,100,2030-01-01\n"
    preview = service.preview(duplicate, AS_OF)
    assert not preview.valid
    assert preview.errors[0].field == "code"
    with pytest.raises(ConvertibleImportError):
        service.import_csv(duplicate, AS_OF, expected_revision=saved.revision)
    assert service.snapshot() == saved


@pytest.mark.parametrize("text", [
    "",
    "code,bond_price\n110001,100\n",
    "code,name,现价,bond_price\n110001,测试,100,100\n",
    "code,name\n110001,测试,多余值\n",
    'code,name\n110001,"未闭合\n',
    "code,name,maturity_date\n110001,测试,2030-02-30\n",
    "code,name\n../outside,测试\n",
])
def test_malformed_input_is_rejected(text):
    preview = parse_csv(text, AS_OF)
    assert not preview.valid
    assert preview.errors


def test_limits_bound_csv_size_and_rows():
    assert not parse_csv("字" * (MAX_CSV_BYTES // 3 + 1), AS_OF).valid
    text = "code,name\n" + "".join(
        f"{100000 + i},测试{i}\n" for i in range(MAX_ROWS + 1)
    )
    result = parse_csv(text, AS_OF)
    assert not result.valid
    assert any("2000" in issue.message for issue in result.errors)


def test_persistence_preview_is_read_only_and_compare_and_swap(tmp_path):
    service = ConvertibleService(tmp_path)
    assert service.snapshot().items == []
    assert service.snapshot().revision == "0"
    preview = service.preview(CSV, AS_OF)
    assert preview.base_revision == "0"
    assert not service.path.exists()

    saved = service.import_csv(CSV, AS_OF, expected_revision=preview.base_revision)
    assert saved.as_of == AS_OF
    assert saved.source == "用户导入"
    assert saved.revision != "0"
    assert saved.updated_at is not None
    assert ConvertibleService(tmp_path).snapshot() == saved
    with pytest.raises(ConvertibleConflictError):
        service.import_csv(CSV, AS_OF, expected_revision="0")
    assert service.snapshot() == saved


def test_write_failure_keeps_saved_data(tmp_path, monkeypatch):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, AS_OF, expected_revision="0")

    def fail_write(*_args, **_kwargs):
        raise OSError("private/path/cannot-write")

    monkeypatch.setattr("app.services.convertibles_research.atomic_write_text", fail_write)
    with pytest.raises(ConvertibleStoreError) as exc:
        service.import_csv(CSV, AS_OF, expected_revision=saved.revision)
    assert "private/path" not in str(exc.value)
    assert service.snapshot() == saved


def test_unknown_storage_schema_is_never_overwritten(tmp_path):
    service = ConvertibleService(tmp_path)
    service.path.parent.mkdir(parents=True)
    service.path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    original = service.path.read_text(encoding="utf-8")
    with pytest.raises(ConvertibleStoreError):
        service.import_csv(CSV, AS_OF, expected_revision="0")
    assert service.path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("corruption", ["empty", "face_value", "boolean_price"])
def test_malformed_or_unsupported_saved_data_is_not_overwritten(tmp_path, corruption):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, AS_OF, expected_revision="0")
    raw = json.loads(service.path.read_text(encoding="utf-8"))
    if corruption == "empty":
        raw = {}
    elif corruption == "face_value":
        raw["items"][0]["face_value"] = 200
    else:
        raw["items"][0]["bond_price"] = True
    original = json.dumps(raw)
    service.path.write_text(original, encoding="utf-8")
    with pytest.raises(ConvertibleStoreError):
        service.snapshot()
    with pytest.raises(ConvertibleStoreError):
        service.import_csv(CSV, AS_OF, expected_revision=saved.revision)
    assert service.path.read_text(encoding="utf-8") == original


def test_concurrent_import_only_one_writer_wins(tmp_path):
    service = ConvertibleService(tmp_path)

    def write():
        try:
            service.import_csv(CSV, AS_OF, expected_revision="0")
            return "saved"
        except ConvertibleConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert sorted(results) == ["conflict", "saved"]
    assert len(service.snapshot().items) == 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(convertibles, "_service", None)
    registrar = BackendExtensionRegistrar(
        convertibles.EXTENSION_ID, api_version=BACKEND_EXTENSION_API_VERSION
    )
    convertibles.setup(registrar)
    convertibles.startup(ExtensionContext(
        api_version=BACKEND_EXTENSION_API_VERSION,
        data_dir=tmp_path,
        repository=None,
    ))
    app = FastAPI()
    for router in registrar.routers:
        app.include_router(router)
    return TestClient(app)


def test_api_preview_confirm_and_list(client):
    empty = client.get("/api/ext/convertibles").json()
    assert empty["items"] == []
    payload = {"csv_text": CSV, "as_of": AS_OF}
    preview = client.post("/api/ext/convertibles/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["valid"]
    assert client.get("/api/ext/convertibles").json() == empty
    payload.update(expected_revision=preview.json()["base_revision"], confirmed=True)
    saved = client.post("/api/ext/convertibles/import", json=payload)
    assert saved.status_code == 200
    assert saved.json()["items"][0]["double_low"] == 120
    assert client.get("/api/ext/convertibles").json() == saved.json()
    assert client.post("/api/ext/convertibles/import", json=payload).status_code == 409
    template = client.get("/api/ext/convertibles/template")
    assert template.status_code == 200
    assert "code,name,bond_price" in template.text


def test_api_rejects_unconfirmed_bad_rows_and_dates(client):
    payload = {"csv_text": CSV, "as_of": AS_OF, "expected_revision": "0"}
    assert client.post("/api/ext/convertibles/import", json=payload).status_code == 422
    payload["confirmed"] = False
    assert client.post("/api/ext/convertibles/import", json=payload).status_code == 422
    payload["confirmed"] = True
    payload["csv_text"] = CSV.replace(",120,000001", ",0,000001")
    response = client.post("/api/ext/convertibles/import", json=payload)
    assert response.status_code == 422
    assert "errors" in response.json()["detail"]
    invalid_date = {"csv_text": CSV, "as_of": "2026-02-30"}
    assert client.post("/api/ext/convertibles/preview", json=invalid_date).status_code == 422
    assert client.get("/api/ext/convertibles").json()["revision"] == "0"


def test_api_fails_clearly_before_extension_startup(client, monkeypatch):
    monkeypatch.setattr(convertibles, "_service", None)
    response = client.get("/api/ext/convertibles")
    assert response.status_code == 503
    assert "尚未就绪" in response.json()["detail"]


def save_initial_snapshot(client, csv_text=CSV):
    response = client.post("/api/ext/convertibles/import", json={
        "csv_text": csv_text, "as_of": AS_OF, "expected_revision": "0", "confirmed": True,
    })
    assert response.status_code == 200
    return response.json()


def test_sourced_disclosures_never_replace_saved_manual_research(client, monkeypatch):
    from test_convertibles_disclosures import base, source

    from app.services import convertibles_disclosures

    saved = save_initial_snapshot(client)
    original_bytes = convertibles._service.path.read_bytes()
    monkeypatch.setattr(convertibles_disclosures, '_cached',
        lambda symbol, bucket: source(base()).fetch(symbol, today='2026-10-22'))
    response = client.get('/api/ext/convertibles/113063/disclosures')
    assert response.status_code == 200
    assert response.json()['code'] == '113063'
    assert client.get('/api/ext/convertibles').json() == saved
    assert convertibles._service.path.read_bytes() == original_bytes


def test_status_checks_local_configuration_without_fetching_quotes(client):
    provider = TickFlowConvertibleProvider(
        api_key_getter=lambda: "test key",
        client_factory=lambda _key: pytest.fail("status must not open a network client"),
    )
    client.app.dependency_overrides[convertibles.get_quote_service] = (
        lambda: ConvertibleQuoteService(provider)
    )
    response = client.get("/api/ext/convertibles/status")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "tickflow", "configured": True, "mode": "realtime",
        "message": "已配置行情 Key；连接和标的权限将在刷新时验证。条款与公告仍需独立提供。",
        "capabilities": {"quotes": True, "terms": False, "announcements": False},
        "last_refresh_at": None,
    }


def test_refresh_missing_key_empty_list_and_bad_revision_have_explicit_status(client):
    provider = TickFlowConvertibleProvider(api_key_getter=lambda: "")
    client.app.dependency_overrides[convertibles.get_quote_service] = (
        lambda: ConvertibleQuoteService(provider)
    )
    assert client.get("/api/ext/convertibles/status").json()["mode"] == "unconfigured"
    assert client.post("/api/ext/convertibles/refresh", json={
        "expected_revision": "0",
    }).status_code == 422
    saved = save_initial_snapshot(client)
    response = client.post("/api/ext/convertibles/refresh", json={
        "expected_revision": saved["revision"],
    })
    assert response.status_code == 503
    assert client.get("/api/ext/convertibles").json() == saved
    assert client.post("/api/ext/convertibles/refresh", json={
        "expected_revision": "0",
    }).status_code == 409


def test_api_refresh_is_partial_quote_merge_not_research_replacement(client):
    saved = save_initial_snapshot(client)

    class Provider:
        name = "tickflow"

        def configured(self):
            return True

        def quotes(self, symbols):
            assert symbols == ["000001.SZ", "110001.SH"]
            return ConvertibleQuoteBatch(
                quotes={"110001.SH": ConvertibleQuote(
                    symbol="110001.SH", price=132.0, change_pct=10.0,
                    turnover_amount=12300.0, turnover_rate_pct=105.0,
                    quote_at="2026-10-21T15:00:00+08:00",
                )},
                fetched_at="2026-10-21T15:01:00+08:00",
            )

    client.app.dependency_overrides[convertibles.get_quote_service] = (
        lambda: ConvertibleQuoteService(Provider())
    )
    response = client.post("/api/ext/convertibles/refresh", json={
        "expected_revision": saved["revision"],
    })
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["bond_price"] == 132
    assert item["stock_price"] is None
    assert item["stock_quote_at"] is None
    assert item["conversion_price"] == 10
    assert item["maturity_date"] == "2030-01-01"
    assert item["conversion_premium_pct"] is None
    assert item["turnover_rate_pct"] == 105
    assert client.get("/api/ext/convertibles/status").json()["last_refresh_at"] == (
        "2026-10-21T15:01:00+08:00"
    )


def test_analysis_is_read_only_and_research_save_uses_compare_and_swap(client):
    saved = save_initial_snapshot(client, CSV.replace("2030-01-01", "2027-10-21"))
    research = {
        "cash_flows": [{"date": "2027-10-21", "amount": 132}],
        "cash_flows_complete": True,
        "price_basis": "full",
        "discount_rate_pct": 10,
        "events": [{
            "date": AS_OF, "type": "announcement", "title": "用户核对的公告",
            "source_url": "https://www.sse.com.cn/", "note": "测试来源",
        }],
    }
    response = client.post("/api/ext/convertibles/110001/analyze", json={"research": research})
    assert response.status_code == 200
    assert response.json()["ytm_pct"] == pytest.approx(10, abs=1e-6)
    assert response.json()["pure_bond_value"] == pytest.approx(120, abs=1e-6)
    assert client.get("/api/ext/convertibles").json() == saved
    payload = {"research": research, "expected_revision": saved["revision"]}
    response = client.put("/api/ext/convertibles/110001/research", json=payload)
    assert response.status_code == 200
    assert response.json()["revision"] != saved["revision"]
    assert response.json()["items"][0]["research"]["events"][0]["title"] == "用户核对的公告"
    assert client.put("/api/ext/convertibles/110001/research", json=payload).status_code == 409


def test_research_rejects_unsafe_links_and_unknown_codes_without_writes(client):
    saved = save_initial_snapshot(client)
    unsafe = {"research": {"events": [{
        "date": AS_OF, "type": "announcement", "title": "未保存",
        "source_url": "javascript:alert(1)",
    }]}, "expected_revision": saved["revision"]}
    assert client.put("/api/ext/convertibles/110001/research", json=unsafe).status_code == 422
    assert client.post("/api/ext/convertibles/110999/analyze", json={
        "research": {},
    }).status_code == 404
    assert client.put("/api/ext/convertibles/110999/research", json={
        "research": {}, "expected_revision": saved["revision"],
    }).status_code == 404
    assert client.get("/api/ext/convertibles").json() == saved


def test_analysis_detects_stale_editor_revision_and_remains_read_only(client):
    old = save_initial_snapshot(client)
    updated = client.put("/api/ext/convertibles/110001/research", json={
        "research": {"events": [{"date": AS_OF, "type": "announcement", "title": "已更新"}]},
        "expected_revision": old["revision"],
    })
    assert updated.status_code == 200
    current = updated.json()
    assert client.post("/api/ext/convertibles/110001/analyze", json={
        "research": {}, "expected_revision": old["revision"],
    }).status_code == 409
    assert client.post("/api/ext/convertibles/110001/analyze", json={
        "research": {}, "expected_revision": current["revision"],
    }).status_code == 200
    assert client.post("/api/ext/convertibles/110001/analyze", json={
        "research": {},
    }).status_code == 200  # old callers remain compatible
    assert client.get("/api/ext/convertibles").json() == current


def test_backup_restore_previews_without_writes_and_preserves_research(client):
    saved = save_initial_snapshot(client)
    backup = dict(saved)
    backup["items"] = [dict(saved["items"][0], research={
        "events": [{"date": AS_OF, "type": "announcement", "title": "备份中的研究"}],
    })]
    backup["items"][0]["double_low"] = 999999
    response = client.post("/api/ext/convertibles/restore/preview", json={"snapshot": backup})
    assert response.status_code == 200
    assert response.json()["valid"]
    assert response.json()["base_revision"] == saved["revision"]
    assert response.json()["items"][0]["double_low"] == 120
    assert client.get("/api/ext/convertibles").json() == saved
    payload = {"snapshot": backup, "expected_revision": saved["revision"], "confirmed": True}
    response = client.post("/api/ext/convertibles/restore", json=payload)
    assert response.status_code == 200
    restored = response.json()
    assert restored["revision"] != saved["revision"]
    assert restored["items"][0]["research"]["events"][0]["title"] == "备份中的研究"
    assert restored["items"][0]["double_low"] == 120
    assert client.post("/api/ext/convertibles/restore", json=payload).status_code == 409


@pytest.mark.parametrize("invalid", ["schema", "empty", "date", "duplicate", "unconfirmed"])
def test_invalid_restore_never_replaces_the_current_snapshot(client, invalid):
    saved = save_initial_snapshot(client)
    backup = dict(saved)
    payload = {"snapshot": backup, "expected_revision": saved["revision"], "confirmed": True}
    if invalid == "schema":
        backup["schema_version"] = 999
    elif invalid == "empty":
        backup["items"] = []
    elif invalid == "date":
        backup["as_of"] = None
    elif invalid == "duplicate":
        backup["items"] = [saved["items"][0], saved["items"][0]]
    else:
        payload["confirmed"] = False
    response = client.post("/api/ext/convertibles/restore", json=payload)
    assert response.status_code == 422
    assert client.get("/api/ext/convertibles").json() == saved
