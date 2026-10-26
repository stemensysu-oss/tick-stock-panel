from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.services.convertibles_research import (
    ConvertibleConflictError,
    ConvertibleResearch,
    ConvertibleService,
    ConvertibleSnapshot,
    ConvertibleStoreError,
    parse_csv,
)

CSV = "code,name,bond_price,stock_price,conversion_price,maturity_date\n110001,研究债,100,10,10,2027-01-01\n"


def test_extended_csv_keeps_units_negative_pb_and_turnover_above_100():
    parsed = parse_csv(
        "转债代码,转债名称,现价,正股价,转股价,正股PB,剩余规模(亿元),成交额(万元),换手率(%),流通市值(亿元),强赎触发比例(%),回售触发比例(%)\n"
        "110001,研究债,120,10,10,-2,3,200,150,20,130,70\n", "2026-01-01",
    )
    assert parsed.valid, parsed.errors
    item = parsed.items[0]
    assert item.stock_pb == -2
    assert item.outstanding_amount == 300_000_000
    assert item.turnover_amount == 2_000_000
    assert item.turnover_rate_pct == 150
    assert item.debt_to_float_cap_pct == 15
    assert item.call_trigger_price == 13
    assert item.put_trigger_price == 7


def test_research_update_is_atomic_and_old_schema_roundtrip_is_supported(tmp_path):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    raw = json.loads(service.path.read_text(encoding='utf-8'))
    old_fields = {"code", "name", "bond_price", "stock_price", "conversion_price", "maturity_date"}
    raw["items"] = [{k: v for k, v in raw["items"][0].items() if k in old_fields}]
    service.path.write_text(json.dumps(raw), encoding='utf-8')
    current = service.snapshot()
    assert current.items[0].research is None
    updated = service.update_research("110001", ConvertibleResearch(
        cash_flows=[{"date": "2027-01-01", "amount": 110}], cash_flows_complete=True,
        discount_rate_pct=5, price_basis="full",
    ), expected_revision=current.revision)
    assert updated.items[0].ytm_pct == 10
    assert service.snapshot() == updated
    with pytest.raises(ConvertibleConflictError):
        service.update_research("110001", ConvertibleResearch(), expected_revision=saved.revision)
    assert service.snapshot() == updated


def test_quote_merge_preserves_research_and_does_not_allow_terms_overwrite(tmp_path):
    service = ConvertibleService(tmp_path)
    old = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    old = service.update_research("110001", ConvertibleResearch(events=[{
        "date": "2026-01-01", "type": "announcement", "title": "已核对募集条款",
        "source_url": "https://example.org/notice",
    }]), expected_revision=old.revision)
    refreshed = service.merge_quotes({"110001": {
        "bond_price": 110, "bond_change_pct": 1.5,
        "quote_at": "2026-01-02T15:00:00+08:00", "quote_source": "测试行情",
    }}, expected_revision=old.revision, as_of="2026-01-02", source="测试行情")
    assert refreshed.items[0].bond_price == 110
    assert refreshed.items[0].research == old.items[0].research
    assert refreshed.items[0].conversion_price == 10
    assert refreshed.items[0].double_low == 120
    with pytest.raises(ValueError):
        service.merge_quotes({"110001": {"conversion_price": 1}},
                             expected_revision=refreshed.revision,
                             as_of="2026-01-02", source="测试行情")
    assert service.snapshot() == refreshed


def test_stale_quotes_do_not_overwrite_newer_quotes(tmp_path):
    service = ConvertibleService(tmp_path)
    old = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    fresh = service.merge_quotes({"110001": {
        "bond_price": 110, "quote_at": "2026-01-02T15:00:00+08:00",
    }}, expected_revision=old.revision, as_of="2026-01-02", source="测试")
    with pytest.raises(ValueError):
        service.merge_quotes({"110001": {
            "bond_price": 90, "quote_at": "2026-01-01T15:00:00+08:00",
        }}, expected_revision=fresh.revision, as_of="2026-01-01", source="测试")
    assert service.snapshot() == fresh


def test_research_contract_rejects_duplicate_dates_bad_link_and_inconsistent_window():
    with pytest.raises(ValidationError):
        ConvertibleResearch(cash_flows=[
            {"date": "2027-01-01", "amount": 5}, {"date": "2027-01-01", "amount": 105},
        ])
    with pytest.raises(ValidationError):
        ConvertibleResearch(events=[{"date": "2026-01-01", "type": "call", "title": "公告",
                                     "source_url": "javascript:alert(1)"}])
    with pytest.raises(ValidationError):
        ConvertibleResearch(call_clause={"window_days": 3, "required_days": 4,
                                         "trigger_ratio_pct": 130})


def test_research_save_size_guard_does_not_replace_previous_data(tmp_path, monkeypatch):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    monkeypatch.setattr("app.services.convertibles_research.MAX_STORED_BYTES", 100)
    with pytest.raises(ConvertibleStoreError):
        service.update_research("110001", ConvertibleResearch(), expected_revision=saved.revision)
    monkeypatch.undo()
    assert service.snapshot() == saved


def test_daily_csv_import_preserves_same_bond_research_in_preview_and_commit(tmp_path):
    service = ConvertibleService(tmp_path)
    initial = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    research = ConvertibleResearch(
        cash_flows=[{"date": "2027-01-01", "amount": 110}], cash_flows_complete=True,
        price_basis="full",
    )
    saved = service.update_research("110001", research, expected_revision=initial.revision)
    next_csv = CSV.replace(",100,10,10,", ",105,10,10,")
    preview = service.preview(next_csv, "2026-01-02")
    assert preview.items[0].research == research
    assert preview.items[0].ytm_pct is not None
    assert any("研究记录保留" in message for message in preview.warnings)
    final = service.import_csv(next_csv, "2026-01-02", expected_revision=saved.revision)
    assert final.items == preview.items
    assert final.items[0].bond_price == 105


def test_changed_bond_binding_does_not_silently_reuse_research(tmp_path):
    from app.services.convertibles_research import ConvertibleImportError

    service = ConvertibleService(tmp_path)
    csv = "code,name,stock_code\n110001,研究债,600001.SH\n"
    initial = service.import_csv(csv, "2026-01-01", expected_revision="0")
    saved = service.update_research("110001", ConvertibleResearch(events=[{
        "date": "2026-01-01", "type": "announcement", "title": "条款备忘",
    }]), expected_revision=initial.revision)
    replacement = csv.replace("600001.SH", "600002.SH")
    assert not service.preview(replacement, "2026-01-02").valid
    with pytest.raises(ConvertibleImportError):
        service.import_csv(replacement, "2026-01-02", expected_revision=saved.revision)
    assert service.snapshot() == saved


def test_complete_backup_roundtrip_recomputes_metrics_and_keeps_research(tmp_path):
    service = ConvertibleService(tmp_path)
    saved = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    saved = service.update_research("110001", ConvertibleResearch(
        cash_flows=[{"date": "2027-01-01", "amount": 110}], cash_flows_complete=True,
        price_basis="full", events=[{"date": "2026-01-01", "type": "call", "title": "公告摘记"}],
    ), expected_revision=saved.revision)
    raw = saved.model_dump()
    raw["items"][0]["double_low"] = 99999
    raw["items"][0]["ytm_pct"] = -99999
    backup = ConvertibleSnapshot.model_validate(raw)
    preview = service.preview_restore(backup)
    assert preview.valid
    assert preview.items[0].double_low == 100
    assert preview.items[0].ytm_pct == 10
    assert service.snapshot() == saved  # preview never writes
    restored = service.restore_backup(backup, expected_revision=preview.base_revision)
    assert restored.revision != backup.revision
    assert restored.items[0].research == backup.items[0].research
    assert restored.items == preview.items
    assert service.snapshot() == restored
    with pytest.raises(ConvertibleConflictError):
        service.restore_backup(backup, expected_revision=saved.revision)
    assert service.snapshot() == restored


def test_backup_rejects_future_schema_empty_or_duplicate_identities(tmp_path):
    with pytest.raises(ValidationError):
        ConvertibleSnapshot.model_validate({"schema_version": 2, "items": []})
    with pytest.raises(ValidationError):
        ConvertibleSnapshot.model_validate({"schema_version": True, "items": []})
    service = ConvertibleService(tmp_path)
    assert not service.preview_restore(ConvertibleSnapshot()).valid
    saved = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    duplicate = saved.model_copy(update={"items": [saved.items[0], saved.items[0]]})
    assert not service.preview_restore(duplicate).valid


def test_extreme_csv_numbers_and_timezone_overflow_return_validation_errors():
    for header, value in (
        ("outstanding_amount", "1e1000000"),
        ("quote_at", "9999-12-31T23:59:59-12:00"),
    ):
        preview = parse_csv(f"code,name,{header}\n110001,研究债,{value}\n", "2026-10-21")
        assert not preview.valid
        assert preview.errors[0].field == header


def test_restore_preview_checks_final_recomputed_payload_size(tmp_path, monkeypatch):
    from app.services.convertibles_models import ConvertibleItem

    backup = ConvertibleSnapshot(as_of="2026-01-01", items=[ConvertibleItem(
        code="110001", name="研究债", bond_price=100, maturity_date="2027-01-01",
        research=ConvertibleResearch(
            cash_flows=[{"date": "2027-01-01", "amount": 110}], cash_flows_complete=True,
            price_basis="full",
        ),
    )])
    # The backup itself fits; generated metadata, derived fields and warnings do not.
    monkeypatch.setattr("app.services.convertibles_research.MAX_STORED_BYTES",
                        len(backup.model_dump_json().encode("utf-8")) + 100)
    service = ConvertibleService(tmp_path)
    preview = service.preview_restore(backup)
    assert not preview.valid
    assert "重算后" in preview.errors[0].message
    assert not service.path.exists()


def test_analysis_is_pinned_to_the_declared_snapshot_revision(tmp_path):
    service = ConvertibleService(tmp_path)
    old = service.import_csv(CSV, "2026-01-01", expected_revision="0")
    newer = service.import_csv(CSV.replace(",100,10,10,", ",105,10,10,"),
                               "2026-01-02", expected_revision=old.revision)
    research = ConvertibleResearch(
        cash_flows=[{"date": "2027-01-01", "amount": 110}], cash_flows_complete=True,
        price_basis="full",
    )
    with pytest.raises(ConvertibleConflictError):
        service.analyze_research("110001", research, expected_revision=old.revision)
    result = service.analyze_research("110001", research, expected_revision=newer.revision)
    assert result.bond_price == 105
    assert result.ytm_pct is not None
    assert service.snapshot() == newer


def test_announcement_notes_accept_normal_lines_but_reject_other_controls():
    event = {"date": "2026-10-21", "type": "announcement", "title": "公告摘记"}
    note = "第一段\r\n第二段\n\t补充"
    research = ConvertibleResearch(events=[{**event, "note": note}])
    assert research.events[0].note == note
    with pytest.raises(ValidationError):
        ConvertibleResearch(events=[{**event, "note": "不合法\x00内容"}])
    with pytest.raises(ValidationError):
        ConvertibleResearch(events=[{**event, "title": "标题\n禁止换行"}])
