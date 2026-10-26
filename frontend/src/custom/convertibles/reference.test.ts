import { expect, it } from 'vitest'
import type { ConvertibleItem, ConvertibleReference } from '@/lib/api'
import { withReference } from './reference'
import { createConvertibleCsv } from './export'
import { DEFAULT_COLUMNS } from './columns'
import { filterConvertibles, sortConvertibles, EMPTY_FILTERS } from './filter'

const item = { code: '113052.SH', name: '合成测试', maturity_date: null, pure_bond_value: null, credit_rating: null } as ConvertibleItem
const ref = { code: '113052.SH', maturity_date: '2027-10-25', pure_bond_value: 98.5, valuation_date: '2026-10-23', credit_rating: 'AAA' } as ConvertibleReference

it('参考仅填未知值，估值日期独立且不改变输入', () => {
  const view = withReference(item, ref, '2026-10-25')
  expect(view.maturity_date).toBe('2027-10-25')
  expect(view.remaining_years).toBe(1)
  expect(view.pure_bond_value_date).toBe('2026-10-23')
  expect(item.maturity_date).toBeNull()
  expect(item.pure_bond_value).toBeNull()
})

it('手工输入与试算优先，未知值不填面值或默认期限', () => {
  const manual = { ...item, maturity_date: '2028-10-25', pure_bond_value: 102, remaining_years: 2, credit_rating: 'AA' }
  const view = withReference(manual, ref, '2026-10-25')
  expect(view.pure_bond_value).toBe(102)
  expect(view.pure_bond_value_basis).toBe('手工模型试算')
  expect(view.pure_bond_value_date).toBe('2026-10-25')
  expect(view.maturity_date).toBe('2028-10-25')
  expect(view.credit_rating).toBe('AA')
  expect(withReference(item, undefined, '2026-10-25').pure_bond_value).toBeNull()
})

it('新参考支持期限筛选及纯债排序，CSV附带估值口径和日期', () => {
  const view = withReference(item, ref, '2026-10-25')
  expect(filterConvertibles([view], { ...EMPTY_FILTERS, maxYears: '1', rating: 'AAA' })).toHaveLength(1)
  expect(sortConvertibles([{ ...view, code: '113053.SH', pure_bond_value: null }, view], 'pure_bond_value', 'asc')[0].code).toBe('113052.SH')
  const csv = createConvertibleCsv([view], ['code', 'pure_bond_value'])
  expect(csv).toContain('pure_bond_value_basis')
  expect(csv).toContain('2026-10-23')
  expect(DEFAULT_COLUMNS).toEqual(expect.arrayContaining(['maturity_date', 'remaining_years', 'pure_bond_value', 'pure_bond_value_date']))
})
