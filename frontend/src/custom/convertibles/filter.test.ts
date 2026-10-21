import { describe, expect, it } from 'vitest'
import type { ConvertibleItem } from '@/lib/api'
import { filterConvertibles, sortConvertibles } from './filter'

function item(code: string, values: Partial<ConvertibleItem> = {}): ConvertibleItem {
  return {
    code, name: `转债${code}`, stock_code: null, stock_name: null,
    bond_price: null, stock_price: null, conversion_price: null, face_value: 100,
    maturity_date: null, redemption_status: null, conversion_value: null,
    conversion_premium_pct: null, double_low: null, ...values,
  }
}

describe('可转债研究筛选与排序', () => {
  it('将未知值置后，无论升降序；不把未知值当作零', () => {
    const rows = [item('100001'), item('100002', { double_low: 0 }), item('100003', { double_low: 120 })]
    expect(sortConvertibles(rows, 'double_low', 'asc').map(row => row.code)).toEqual(['100002', '100003', '100001'])
    expect(sortConvertibles(rows, 'double_low', 'desc').map(row => row.code)).toEqual(['100003', '100002', '100001'])
    expect(rows[0].code).toBe('100001')
  })

  it('零溢价上限排除正溢价和缺值，保留零与负溢价', () => {
    const rows = [item('100001'), item('100002', { conversion_premium_pct: 0 }), item('100003', { conversion_premium_pct: -5 }), item('100004', { conversion_premium_pct: 10 })]
    expect(filterConvertibles(rows, { search: '', maxPrice: '', maxPremium: '0', maxDoubleLow: '' }).map(row => row.code)).toEqual(['100002', '100003'])
  })

  it('无阈值时保留未知数据，并支持正股名称与代码搜索', () => {
    const rows = [item('100001', { stock_code: '000001.SZ', stock_name: '测试正股' }), item('100002')]
    const filters = { search: '', maxPrice: '', maxPremium: '', maxDoubleLow: '' }
    expect(filterConvertibles(rows, filters)).toHaveLength(2)
    expect(filterConvertibles(rows, { ...filters, search: '000001.sz' })).toHaveLength(1)
    expect(filterConvertibles(rows, { ...filters, search: '测试正股' })[0].code).toBe('100001')
  })

  it('按亿元筛选剩余本金，并组合评级、行业、收益率和剩余期限', () => {
    const rows = [
      item('100001', { outstanding_amount: 300_000_000, credit_rating: 'AA', industry: '制造业', ytm_pct: 3, remaining_years: 1.5 }),
      item('100002', { outstanding_amount: 700_000_000, credit_rating: 'AA', industry: '制造业', ytm_pct: 4, remaining_years: 1 }),
      item('100003', { outstanding_amount: 100_000_000, credit_rating: 'AA+', industry: '制造业', ytm_pct: 5, remaining_years: 1 }),
      item('100004', { outstanding_amount: 100_000_000, credit_rating: 'AA', industry: '制造业', ytm_pct: null, remaining_years: 1 }),
    ]
    expect(filterConvertibles(rows, {
      search: '', maxPrice: '', maxPremium: '', maxDoubleLow: '',
      maxSize: '5', rating: 'AA', industry: '制造业', minYield: '2', maxYears: '2',
    }).map(row => row.code)).toEqual(['100001'])
  })

  it('新增字段尚不存在的旧快照与显式null同样排最后，负收益率正常排序', () => {
    const rows = [item('100001'), item('100002', { ytm_pct: -12 }), item('100003', { ytm_pct: 3 }), item('100004', { ytm_pct: null })]
    expect(sortConvertibles(rows, 'ytm_pct', 'desc').map(row => row.code)).toEqual(['100003', '100002', '100001', '100004'])
  })
})
