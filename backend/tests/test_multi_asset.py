import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom import multi_asset
from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.services.multi_asset import (
    MultiAssetConflictError,
    MultiAssetImportError,
    MultiAssetService,
    MultiAssetStoreError,
    calculate_metrics,
    parse_csv,
)
from app.services.multi_asset_models import AssetInput

CSV = ('code,name,currency,source_name,as_of,price,price_as_of,nav,nav_currency,nav_as_of\n'
       'TEST-1,测试基金,CNY,手工测试,2026-01-15,1.1,2026-01-15,1,CNY,2026-01-15\n')


def test_nav_premium_and_fail_closed_inputs():
    row = parse_csv('etf', CSV)[0]
    assert calculate_metrics('etf', row)[0]['nav_premium_pct'] == pytest.approx(10)
    for updates in ({'nav': None}, {'nav_currency': 'USD'}, {'nav_as_of': '2026-01-14'},
                    {'price_as_of': None}, {'as_of': '2026-01-16'}):
        metrics, warnings = calculate_metrics('etf', row.model_copy(update=updates))
        assert metrics['nav_premium_pct'] is None
        assert warnings


def test_ah_fx_direction_deal_and_dividend_period():
    common = dict(code='TEST', name='测试', currency='CNY', source_name='测试',
                  as_of='2026-01-15', price=11.0, price_as_of='2026-01-15')
    row = AssetInput(**common, h_code='TEST-H', h_price=10.0, h_currency='HKD',
                     h_price_as_of='2026-01-15', fx_hkd_cny=0.88, fx_as_of='2026-01-15')
    assert calculate_metrics('ah', row)[0]['ah_premium_pct'] == pytest.approx(25)
    assert calculate_metrics('ah', row.model_copy(update={'fx_as_of': '2026-01-14'}))[0]['ah_premium_pct'] is None
    row = AssetInput(**common, deal_price=12.0, deal_currency='CNY', deal_as_of='2026-01-15')
    assert calculate_metrics('arbitrage', row)[0]['deal_spread_pct'] == pytest.approx(100 / 11)
    row = AssetInput(**common, dividend_per_share=0.55, dividend_currency='CNY',
                     dividend_period_start='2025-01-16', dividend_period_end='2026-01-15',
                     dividend_basis='trailing_12_months')
    assert calculate_metrics('dividends', row)[0]['dividend_yield_pct'] == pytest.approx(5)
    for updates in ({'dividend_basis': None}, {'dividend_period_start': '2024-01-01'},
                    {'dividend_period_end': '2026-01-16'}, {'dividend_currency': 'USD'}):
        assert calculate_metrics('dividends', row.model_copy(update=updates))[0]['dividend_yield_pct'] is None


@pytest.mark.parametrize('replacement', ['0', '-1', 'NaN', 'Infinity', '1e999', 'true'])
def test_invalid_price_rejected(replacement):
    with pytest.raises(MultiAssetImportError):
        parse_csv('etf', CSV.replace(',1.1,', f',{replacement},'))


def test_import_structure_and_provenance_rejected():
    invalid = [CSV + CSV.splitlines()[1] + '\n', CSV.replace('2026-01-15', '2026-02-30'),
               CSV.replace('code,name', 'code,code'), CSV.replace('nav_as_of', 'data_status'),
               CSV.replace('TEST-1', '=HYPERLINK("bad")'), CSV + 'extra,column\n',
               CSV.replace('source_name', 'source_url'), CSV.replace('CNY', 'BTC')]
    for text in invalid:
        with pytest.raises(MultiAssetImportError):
            parse_csv('etf', text)
    with pytest.raises(MultiAssetImportError):
        parse_csv('etf', CSV.splitlines()[0] + '\n')


def test_atomic_revision_category_preservation_and_demo_isolation(tmp_path):
    service = MultiAssetService(tmp_path)
    preview = service.preview('etf', CSV, expected_revision='0')
    assert preview['row_count'] == 1
    assert not service.path.exists()
    assert service.snapshot('etf', 'demo')['data_status'] == 'demo'
    assert not service.path.exists()
    saved = service.import_csv('etf', CSV, expected_revision='0')
    assert saved['data_status'] == 'imported'
    assert MultiAssetService(tmp_path).snapshot('etf') == saved
    cash = 'code,name,currency,source_name,as_of,rate_pct\nTEST-C,测试现金,CNY,测试,2026-01-15,2.5\n'
    service.import_csv('cash', cash, expected_revision=saved['revision'])
    assert service.snapshot('etf')['rows'] == saved['rows']
    assert service.snapshot('cash')['rows'][0]['rate_pct'] == 2.5
    with pytest.raises(MultiAssetConflictError):
        service.import_csv('etf', CSV, expected_revision=saved['revision'])
    assert 'DEMO' not in service.path.read_text(encoding='utf-8')
    assert parse_csv('etf', service.export_csv('etf'))[0].code == 'TEST-1'


def test_all_demo_categories_are_fictional_and_cover_missing_inputs(tmp_path):
    from app.services.multi_asset_catalog import catalog

    service = MultiAssetService(tmp_path)
    for category in catalog()['categories']:
        snapshot = service.snapshot(category['id'], 'demo')
        assert len(snapshot['rows']) == 3
        assert all(row['code'].startswith('DEMO-') and row['data_status'] == 'demo'
                   for row in snapshot['rows'])
        assert snapshot['rows'][-1]['price'] is None
        assert all(value is None for value in snapshot['rows'][-1]['metrics'].values())
    assert not service.path.exists()


def test_index_catalog_distinguishes_points_from_currency():
    from app.services.multi_asset_catalog import catalog

    indices = next(item for item in catalog()['categories'] if item['id'] == 'indices')
    for fields in (indices['fields'], indices['columns']):
        price = next(field for field in fields if field['key'] == 'price')
        currency = next(field for field in fields if field['key'] == 'currency')
        assert price['label'] == '点位' and price['unit'] == '点'
        assert '非金额' in currency['label'] and '不参与汇率计算' in currency['description']


def test_concurrent_writers_only_one_succeeds(tmp_path):
    def write():
        try:
            MultiAssetService(tmp_path).import_csv('etf', CSV, expected_revision='0')
            return 'saved'
        except MultiAssetConflictError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: write(), range(2))) == ['conflict', 'saved']


@pytest.mark.parametrize('contents', ['bad JSON', '{"schema_version":2}',
    '{"revision":"x"}', '{"schema_version":true,"revision":"x"}',
    '{"schema_version":1,"revision":"x","categories":{"unknown":[]}}'])
def test_corrupt_or_newer_store_never_overwritten(tmp_path, contents):
    service = MultiAssetService(tmp_path)
    service.path.parent.mkdir(parents=True)
    service.path.write_text(contents, encoding='utf-8')
    with pytest.raises(MultiAssetStoreError):
        service.import_csv('etf', CSV, expected_revision='0')
    assert service.path.read_text(encoding='utf-8') == contents
    assert service.snapshot('etf', 'demo')['data_status'] == 'demo'


def test_write_failure_preserves_snapshot(tmp_path, monkeypatch):
    service = MultiAssetService(tmp_path)
    saved = service.import_csv('etf', CSV, expected_revision='0')
    def fail_write(*_args, **_kwargs):
        raise OSError('disk full')
    monkeypatch.setattr('app.services.multi_asset.atomic_write_text', fail_write)
    with pytest.raises(MultiAssetStoreError):
        service.import_csv('etf', CSV, expected_revision=saved['revision'])
    assert service.snapshot('etf') == saved


def test_limits_and_store_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr('app.services.multi_asset.MAX_CSV_BYTES', 10)
    with pytest.raises(MultiAssetImportError):
        parse_csv('etf', CSV)
    monkeypatch.setattr('app.services.multi_asset.MAX_CSV_BYTES', 2 * 1024 * 1024)
    service = MultiAssetService(tmp_path)
    saved = service.import_csv('etf', CSV, expected_revision='0')
    contents = json.loads(service.path.read_text(encoding='utf-8'))
    contents['categories']['etf'][0]['data_status'] = 'verified_live'
    service.path.write_text(json.dumps(contents), encoding='utf-8')
    with pytest.raises(MultiAssetStoreError):
        service.snapshot('etf')
    with pytest.raises(MultiAssetStoreError):
        service.import_csv('etf', CSV, expected_revision=saved['revision'])


def test_csv_export_neutralizes_formulas_and_preserves_numeric_units(tmp_path):
    service = MultiAssetService(tmp_path)
    content = ('code,name,currency,source_name,as_of,change_pct,notes\n'
               'TEST,=1+1,CNY,测试,2026-01-15,-2.5,@formula\n')
    saved = service.import_csv('indices', content, expected_revision='0')
    exported = service.export_csv('indices')
    assert "'=1+1" in exported and "'@formula" in exported
    assert saved['rows'][0]['change_pct'] == -2.5
    assert '-2.5' in exported and "'-2.5" not in exported


def test_strict_models_and_csv_boundaries(monkeypatch):
    from pydantic import ValidationError

    from app.custom.multi_asset import ImportRequest

    for confirmed in (False, 1, 'true'):
        with pytest.raises(ValidationError):
            ImportRequest(category='etf', csv_text=CSV, expected_revision='0',
                          confirmed=confirmed)
    row = parse_csv('etf', CSV)[0].model_dump()
    for value in (True, '1.1'):
        with pytest.raises(ValidationError):
            AssetInput.model_validate({**row, 'price': value})
    monkeypatch.setattr('app.services.multi_asset.MAX_ROWS', 1)
    with pytest.raises(MultiAssetImportError):
        parse_csv('etf', CSV + CSV.splitlines()[1].replace('TEST-1', 'TEST-2') + '\n')
    for source_url in ('javascript:alert(1)', 'https://user:secret@example.test/data'):
        with pytest.raises(ValidationError):
            AssetInput.model_validate({**row, 'source_url': source_url})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(multi_asset, '_service', None)
    registrar = BackendExtensionRegistrar(multi_asset.EXTENSION_ID,
                                          api_version=BACKEND_EXTENSION_API_VERSION)
    multi_asset.setup(registrar)
    multi_asset.startup(ExtensionContext(api_version=BACKEND_EXTENSION_API_VERSION,
                                       data_dir=tmp_path, repository=None))
    app = FastAPI()
    for router in registrar.routers:
        app.include_router(router)
    return TestClient(app)


def test_api_catalog_preview_confirmation_conflict_and_export(client):
    catalog = client.get('/api/multi-asset/catalog').json()
    assert len(catalog['categories']) == 13
    assert {c['id'] for c in catalog['categories'] if c['live_status'] == 'available'} == {
        'etf', 'lof', 'cash', 'reits', 'indices', 'bonds', 'hk', 'ah', 'qdii', 'dividends', 'ipo'}
    assert client.get('/api/multi-asset/snapshot?category=etf').json()['data_status'] == 'empty'
    payload = dict(category='etf', csv_text=CSV, expected_revision='0')
    assert client.post('/api/multi-asset/import/preview', json=payload).json()['row_count'] == 1
    assert client.post('/api/multi-asset/import', json=payload).status_code == 422
    payload['confirmed'] = True
    response = client.post('/api/multi-asset/import', json=payload)
    assert response.status_code == 200
    assert response.json()['rows'][0]['metrics']['nav_premium_pct'] == pytest.approx(10)
    assert client.post('/api/multi-asset/import', json=payload).status_code == 409
    assert client.get('/api/multi-asset/export?category=etf').text.startswith('\ufeffcode,name')
    assert client.get('/api/multi-asset/template?category=etf').status_code == 200
    assert client.get('/api/multi-asset/snapshot?category=unknown').status_code == 422
    assert client.get('/api/multi-asset/snapshot?category=etf&mode=live').status_code == 422


def test_api_unavailable_and_validation_are_clear(client, monkeypatch):
    payload = dict(category='etf', csv_text=CSV.replace(',1.1,', ',NaN,'), expected_revision='0')
    response = client.post('/api/multi-asset/import/preview', json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], str)
    monkeypatch.setattr(multi_asset, '_service', None)
    assert client.get('/api/multi-asset/snapshot?category=etf').status_code == 503
    assert client.get('/api/multi-asset/catalog').status_code == 200
