"""Live, credential-free checks shared by installed Windows and macOS builds."""
from __future__ import annotations


def check_enrichment(base, request, require):
    def get(route):
        return request(base, route, timeout=180)
    money = get('/api/ext/funds/000009.OF/nav?range=month')
    require(money['series_kind'] == 'money' and len(money['items']) >= 20, 'Money income series missing')
    require(all(p['unit_nav'] is None and p['adj_nav'] is None and p['cumulative_nav'] is None for p in money['items']),
        'Money income was mislabeled as NAV')
    last = money['items'][-1]
    require(last['income_per_10000'] is not None and last['seven_day_yield_pct'] is not None, 'Published money yields missing')
    trading = get('/api/ext/funds/000009.OF/trading')
    require(trading['subscription_status'] and trading['redemption_status'], 'Trading states missing')
    require(trading['daily_purchase_limit']['status'] in {'finite', 'unlimited'}, 'Purchase limit unavailable')
    require(trading['minimum_purchase']['unit'] == 'CNY' and trading['minimum_redemption']['unit'] == 'units', 'Trading units wrong')
    dividends = get('/api/ext/funds/510300.SH/dividends')
    first_cash = dividends['items'][0].get('per_ten_cash_before_tax') if dividends['items'] else None
    print(f"Installed fund dividend evidence: provider={dividends.get('provider')}, rows={len(dividends['items'])}, first_per_ten_cash={first_cash}", flush=True)
    require(len(dividends['items']) >= 10 and dividends['items'][0]['per_ten_cash_before_tax'] is not None, 'Historical fund dividends missing')
    holdings = get('/api/ext/funds/000001.OF/holdings?asset_type=bond&report_date=2026-06-30')
    require(bool(holdings['items']) and all(h['asset_type'] == 'bond' and h['report_date'] == '2026-06-30'
        and h['publish_date'] is None for h in holdings['items']), 'Historical bond holding semantics wrong')
    terms = get('/api/ext/convertibles/127068/disclosures')
    require(terms['call_clause_text'] and terms['put_clause_text'] and terms['coupon_text'], 'Bond terms missing')
    require(terms['call_state'] == 'unknown' or terms['call_notice_date'], 'Call implementation has no dated evidence')
    terminated = get('/api/ext/convertibles/113063/disclosures')
    require(terminated['lifecycle'] == 'terminated' and terminated['call_state'] == 'historical_implementation', 'Terminated call history misrepresented')
    require(all(r['provider'] == 'eastmoney_public' for r in [money, trading, dividends, holdings, terms, terminated]), 'Missing public provenance')
    require(terms['attempts'][:2] == [{'provider': 'tickflow', 'status': 'unsupported'}, {'provider': 'fuyao', 'status': 'unsupported'}], 'Unsupported API capability hidden')
    refs = request(base, '/api/ext/convertibles/references', body={'codes': ['113052', '127068', '113063']}, timeout=180)
    lookup = {r['code']: r for r in refs['items']}
    for symbol in ('113052.SH', '127068.SZ'):
        ref = lookup[symbol]
        require(ref['lifecycle'] == 'listed' and ref['maturity_date'] and ref['credit_rating'], 'Listed bond maturity/rating missing')
        require(ref['pure_bond_value'] and ref['valuation_date'] and ref['valuation_close'], 'Dated pure bond valuation missing')
        require(ref['valuation_date'] <= ref['fetched_at'][:10], 'Valuation date fabricated from future')
    require(lookup['113052.SH']['maturity_date'] == '2027-12-27', 'Xingye maturity mapped to conversion end')
    require(lookup['113063.SH']['maturity_date'] is None and lookup['113063.SH']['pure_bond_value'] is None,
            'Terminated source end date misrepresented as maturity/current valuation')
    result = {'money': {'rows': len(money['items']), 'last': last},
        'trading': trading, 'dividends': {'rows': len(dividends['items']), 'first': dividends['items'][0]},
        'bond_holdings': {'rows': len(holdings['items']), 'report_date': holdings['report_date']},
        'terms': {'code': terms['code'], 'lifecycle': terms['lifecycle'], 'call_state': terms['call_state'], 'events': len(terms['events'])},
        'terminated': {'code': terminated['code'], 'call_state': terminated['call_state']},
        'convertible_references': {'items': [{k: r[k] for k in ('code', 'maturity_date', 'source_end_date', 'credit_rating', 'pure_bond_value', 'valuation_date', 'valuation_close', 'lifecycle')} for r in refs['items']], 'attempts': refs['attempts']}}
    print(f"Installed fund/bond enrichment passed: {len(money['items'])} money days, {len(dividends['items'])} dividends, {len(holdings['items'])} bond holdings", flush=True)
    return result
