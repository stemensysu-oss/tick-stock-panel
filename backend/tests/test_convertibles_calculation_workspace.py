import pytest

from app.services import convertibles_calculation_workspace as workspace
from app.services.convertibles_calculation_config import ConvertibleCalculationSettings
from app.services.convertibles_models import ConvertibleResearch
from app.services.convertibles_reference import ConvertibleReferences
from app.services.convertibles_research import ConvertibleConflictError, ConvertibleService
from app.services.convertibles_sources import ConvertibleDataError

CSV = 'code,name,bond_price,stock_price,conversion_price,maturity_date\n110001,测试转债,100,10,10,2027-01-01\n'


def test_calculation_template_roundtrip_and_cas_do_not_rewrite_source(tmp_path, monkeypatch):
    store = ConvertibleService(tmp_path)
    raw = store.import_csv(CSV, '2026-01-01', expected_revision='0')
    config = ConvertibleCalculationSettings(formulas={'double_low': 'bond_price + 2 * conversion_premium_pct'}, parameters={'premium_weight': 2.0})
    saved = store.update_calculation_settings(config, expected_revision=raw.revision)
    assert saved.calculation_settings == config
    monkeypatch.setattr(workspace, 'references', lambda codes: ConvertibleReferences(items=[], fetched_at='2026-01-01', attempts=[], warnings=[]))
    before = store.path.read_bytes()
    result = workspace.calculation_snapshot(store, saved.revision)
    assert result.items[0].double_low == 100
    assert result.items[0].calculation_details['double_low']['custom']
    assert store.path.read_bytes() == before
    with pytest.raises(ConvertibleConflictError):
        store.update_calculation_settings(config, expected_revision=raw.revision)
    restored = ConvertibleService(tmp_path).snapshot()
    assert restored.calculation_settings == config
    imported = store.import_csv(CSV, '2026-01-01', expected_revision=restored.revision)
    assert imported.calculation_settings == config
    recovered = store.restore_backup(saved, expected_revision=imported.revision)
    assert recovered.calculation_settings == config


def test_source_failure_still_computes_manual_cashflows_and_preview_is_transient(tmp_path, monkeypatch):
    store = ConvertibleService(tmp_path)
    snapshot = store.import_csv(CSV, '2026-01-01', expected_revision='0')
    def unavailable(codes):
        raise ConvertibleDataError(502, 'test')
    monkeypatch.setattr(workspace, 'references', unavailable)
    research = ConvertibleResearch(cash_flows=[{'date': '2027-01-01', 'amount': 105}], cash_flows_complete=True, price_basis='full', personal_rating='AA')
    before = store.path.read_bytes()
    result = workspace.calculation_snapshot(store, snapshot.revision, code='110001', research_override=research)
    assert result.reference_status == 'unavailable' and result.warnings
    assert result.items[0].ytm_pct == pytest.approx(5)
    assert result.items[0].personal_rating == 'AA'
    assert store.path.read_bytes() == before
    assert store.snapshot().items[0].research is None


def test_revision_change_during_reference_fetch_rejects_late_result(tmp_path, monkeypatch):
    store = ConvertibleService(tmp_path)
    snapshot = store.import_csv(CSV, '2026-01-01', expected_revision='0')
    def concurrent_write(codes):
        store.update_calculation_settings(ConvertibleCalculationSettings(parameters={'discount_rate_pct': 5.0}), expected_revision=snapshot.revision)
        return ConvertibleReferences(items=[], fetched_at='2026-01-01', attempts=[], warnings=[])
    monkeypatch.setattr(workspace, 'references', concurrent_write)
    with pytest.raises(ConvertibleConflictError):
        workspace.calculation_snapshot(store, snapshot.revision)


def test_unknown_code_and_empty_snapshot_do_not_fetch(tmp_path, monkeypatch):
    def unexpected(codes):
        pytest.fail('must not fetch')
    monkeypatch.setattr(workspace, 'references', unexpected)
    store = ConvertibleService(tmp_path)
    assert workspace.calculation_snapshot(store, '0').items == []
    with pytest.raises(ValueError):
        workspace.calculation_snapshot(store, '0', code='110001')
