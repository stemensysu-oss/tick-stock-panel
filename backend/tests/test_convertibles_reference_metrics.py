from datetime import datetime

import httpx

from app.data_providers.research_market import SH
from app.services.convertibles_reference import ConvertibleReferenceProvider


class HTTP:
    def __init__(self, coherent=True):
        self.coherent = coherent
    def get(self, url, params):
        if 'ulist' in url:
            time = int(datetime(2026, 10, 23, 15, tzinfo=SH).timestamp())
            if '601166' in params['secids']:
                rows = [{'f12': '601166', 'f13': 1, 'f124': time, 'f23': -1.5, 'f21': 5000000000}]
            else:
                rows = [{'f12': '113052', 'f13': 1, 'f124': time, 'f2': 112.0,
                         'f38': 10000000, 'f20': 1120000000 if self.coherent else 300000000,
                         'f241': 109.0}]
            return httpx.Response(200, json={'data': {'diff': rows}})
        if 'reportName' in params:
            rows = [{'SECURITY_CODE': '113052', 'SECUCODE': '113052.SH', 'SECURITY_NAME_ABBR': '合成样本',
                     'PAR_VALUE': 100, 'VALUE_DATE': '2021-12-27', 'BOND_EXPIRE': '6',
                     'LISTING_DATE': '2022-01-14', 'EXPIRE_DATE': '2027-12-27', 'PAY_INTEREST_DAY': '12-27',
                     'CONVERT_STOCK_CODE': '601166', 'RATING': 'AAA', 'PARTY_NAME': '合成机构',
                     'INTEREST_RATE_EXPLAIN': '第一年0.2%，第二年0.4%，第三年1.0%，第四年1.5%，第五年2.3%，第六年3.0%。',
                     'REDEEM_CLAUSE': '到期赎回按面值的109%（含最后一期利息）赎回'}]
        else:
            rows = [{'DATE': '2026-10-23', 'ZCODE': '113052', 'SECUCODE': '113052.SH',
                     'PUREBONDVALUE': 101.0, 'FCLOSE': 112.0}]
        return httpx.Response(200, json={'success': True, 'result': {'data': rows, 'count': len(rows)}})


def test_remaining_face_principal_is_not_market_value_or_issue_size_and_dates_are_honest():
    r = ConvertibleReferenceProvider(HTTP()).fetch(['113052'], today='2026-10-26').items[0]
    assert r.outstanding_units == 10000000
    assert r.outstanding_amount == 1000000000
    assert r.outstanding_amount != r.quantity_market_value
    assert r.outstanding_as_of is None and r.outstanding_observed_at == r.fetched_at
    assert r.stock_pb == -1.5 and r.float_market_cap == 5000000000
    assert r.stock_code == '601166.SH' and r.rating_agency == '合成机构'
    assert r.cashflow_plan['status'] == 'available'
    assert r.cashflow_plan['cash_flows'][-1]['amount'] == 109


def test_quantity_and_market_value_mismatch_keeps_scale_unknown_but_other_fields_work():
    r = ConvertibleReferenceProvider(HTTP(False)).fetch(['113052'], today='2026-10-26').items[0]
    assert r.outstanding_amount is None and r.outstanding_units is None
    assert r.stock_pb == -1.5 and r.cashflow_plan['status'] == 'available'
    assert any('发行规模' in w for w in r.warnings)


def test_datacenter_enrichment_keeps_calculations_available_when_direct_quote_host_is_unavailable():
    class DataCenterOnly(HTTP):
        def get(self, url, params):
            if 'ulist' in url:
                raise ValueError('direct quote host unavailable')
            response = super().get(url, params)
            if 'reportName' in params:
                assert 'f38~10~SECURITY_CODE~CB_UNITS' in params['quoteColumns']
                data = response.json()
                data['result']['data'][0].update(CB_PRICE=112.0, CB_UNITS=10000000,
                    CB_CAP=1120000000, CB_STAMP=int(datetime(2026, 10, 23, 15, tzinfo=SH).timestamp()),
                    STOCK_PB=1.2, STOCK_FLOAT_CAP=5000000000, STOCK_STAMP=int(datetime(2026, 10, 23, 15, tzinfo=SH).timestamp()))
                return httpx.Response(200, json=data)
            return response
    result = ConvertibleReferenceProvider(DataCenterOnly()).fetch(['113052'], today='2026-10-26')
    r = result.items[0]
    assert r.outstanding_amount == 1000000000 and r.stock_pb == 1.2
    assert r.maturity_redemption_price == 109 and r.cashflow_plan['status'] == 'available'
    assert any(a['dataset'] == 'reference_prices' and a['status'] == 'failed' for a in result.attempts)
    assert any(a['dataset'] == 'cb_underlying_metrics_datacenter' and a['status'] == 'success' for a in result.attempts)
