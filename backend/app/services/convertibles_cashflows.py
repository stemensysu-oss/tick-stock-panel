"""Strictly recognized contract-plan cash flows, separate from confirmed research.

Nominal annual dates are not issuer-confirmed payment announcements. The UI must
retain the plan basis and holiday/early-redemption assumptions when computing IRR.
"""
from __future__ import annotations

import math
import re
from datetime import date

_CHINESE = {char: index for index, char in enumerate('一二三四五六七八九十', 1)}
_COUPON = re.compile(r'第([一二三四五六七八九十]|[1-9]\d?)年(?:的)?(?:票面利率|利率)?(?:为|是|[:：])?\s*([0-9]+(?:\.[0-9]+)?)\s*[%％]')


def contract_redemption_price(row):
    """An explicit maturity term, never an inferred face/default payoff."""
    text = re.split(r'有条件赎回', str(row.get('REDEEM_CLAUSE') or ''))[0]
    if '到期赎回' not in text or not re.search(r'含(?:最后一期(?:计息年度|年度|票面)?|最后一年)利息', text):
        return None
    matches = re.findall(r'(?:票面面值|面值)(?:的)?\s*([0-9]+(?:\.[0-9]+)?)\s*[%％]', text)
    if len(matches) != 1:
        return None
    value = float(matches[0])
    return value if 0 < value < 1000 else None


def contract_cash_flows(row, maturity_date, redemption_price, lifecycle):
    result = {'status': 'missing', 'cash_flows': [], 'reasons': [],
              'basis': '合同计划现金流（税前、每张100元；假设不转股且无提前赎回）',
              'warnings': ['年度付息按合同名义日期排期；节假日顺延及实际付息日须核对公告，计划日期不是已公告日期。',
                           '末次兑付已包含末期利息，不再重复加息。']}
    def missing(reason):
        result['reasons'].append(reason)
        return result
    if lifecycle != 'listed' or not maturity_date:
        return missing('尚未确认有效的原合同到期日，或已终止/退市')
    if row.get('NOTICE_DATE_SH') and row.get('EXECUTE_START_DATESH'):
        return missing('已存在赎回实施日期，请核对实施现金流，不沿用普通到期计划')
    try:
        start = date.fromisoformat(str(row.get('VALUE_DATE', ''))[:10])
        end = date.fromisoformat(maturity_date)
        years = float(row.get('BOND_EXPIRE'))
        redemption = float(redemption_price)
    except (ValueError, TypeError):
        return missing('缺少完整起息日、期限或到期兑付金额')
    if not math.isfinite(years) or not years.is_integer() or not 1 <= years <= 10 or not 0 < redemption < 1000:
        return missing('期限或到期兑付金额不在支持范围')
    if row.get('PAY_INTEREST_DAY') != start.strftime('%m-%d'):
        return missing('付息日与起息日周年不一致，不能自动排期')
    coupon_text = row.get('INTEREST_RATE_EXPLAIN') or ''
    coupons = {}
    matches = _COUPON.findall(coupon_text)
    for year, rate in matches:
        number = _CHINESE[year] if year in _CHINESE else int(year)
        if number in coupons or not 0 <= float(rate) <= 100:
            return missing('年度票息重复或数值异常')
        coupons[number] = float(rate)
    if set(coupons) != set(range(1, int(years) + 1)):
        return missing('未取得逐年完整票息，不能由当前票息推断全部现金流')
    text = re.split(r'有条件赎回', str(row.get('REDEEM_CLAUSE') or ''))[0]
    if not re.search(r'含(?:最后一期(?:计息年度|年度|票面)?|最后一年)利息', text):
        return missing('未确认到期兑付金额是否包含最后一期利息')
    amount = re.search(r'(?:票面面值|面值)(?:的)?\s*([0-9]+(?:\.[0-9]+)?)\s*[%％]', text)
    if not amount or abs(float(amount.group(1)) - redemption) > 0.001:
        return missing('到期赎回金额与条款无法互相核对')
    try:
        anniversary = start.replace(year=start.year + int(years))
    except ValueError:
        return missing('闰日付息排期需人工确认')
    if abs((end - anniversary).days) > 7:
        return missing('到期日与期限不一致')
    flows = []
    for year in range(1, int(years)):
        try:
            day = start.replace(year=start.year + year)
        except ValueError:
            return missing('闰日付息排期需人工确认')
        # A zero coupon creates no payment; zero is not a fabricated absence.
        if coupons[year] > 0:
            flows.append({'date': day.isoformat(), 'amount': coupons[year]})
    flows.append({'date': end.isoformat(), 'amount': redemption})
    result.update(status='available', cash_flows=flows)
    return result
