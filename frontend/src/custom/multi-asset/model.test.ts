// @vitest-environment jsdom
import { beforeEach, expect, it } from 'vitest'
import type { MultiAssetRow } from '@/lib/api'
import { filterRows, formatCell, readPreferences, safeSourceUrl, valueOf, type Preferences } from './model'

const row = (code: string, value: number | null): MultiAssetRow => ({ code, name: code, source_name: '手动资料', as_of: '2026-01-02', currency: 'CNY', data_status: 'imported', metrics: { nav_premium_pct: value }, warnings: [], price: 1 })
const base: Preferences = { search: '', watched: [], watchOnly: false, columns: [], sortKey: 'nav_premium_pct', descending: true }
beforeEach(() => localStorage.clear())

it('缺失值不变成 0，零值保持有效，按百分数显示且不隐式乘 100', () => {
  expect(valueOf(row('A', null), 'nav_premium_pct')).toBeNull()
  expect(formatCell(row('A', null), { key: 'nav_premium_pct', label: '溢价', type: 'number', unit: '%' })).toBe('--')
  expect(formatCell(row('A', 0), { key: 'nav_premium_pct', label: '溢价', type: 'number', unit: '%' })).toBe('0%')
  expect(formatCell(row('A', 0.5), { key: 'nav_premium_pct', label: '溢价', type: 'number', unit: '%' })).toBe('0.5%')
})
it('升降序都将缺失指标置后，自选只保留相同标识', () => {
  const rows = [row('missing', null), row('zero', 0), row('positive', 5)]
  expect(filterRows(rows, base).map(item => item.code)).toEqual(['positive', 'zero', 'missing'])
  expect(filterRows(rows, { ...base, descending: false }).map(item => item.code)).toEqual(['zero', 'positive', 'missing'])
  expect(filterRows(rows, { ...base, watchOnly: true, watched: ['zero'] }).map(item => item.code)).toEqual(['zero'])
})
it('只生成 http(s) 来源链接，拒绝脚本、相对地址与含凭据 URL', () => {
  expect(safeSourceUrl('https://example.com/report')).toBe('https://example.com/report')
  for (const value of ['javascript:alert(1)', 'data:text/html,test', '//example.com', 'https://user:pass@example.com', null]) expect(safeSourceUrl(value)).toBeNull()
})
it('损坏偏好安全回退，演示和导入使用独立存储键', () => {
  const columns = [{ key: 'price', label: '价格', type: 'number' as const }]
  localStorage.setItem('demo', JSON.stringify({ watched: ['DEMO-1'], columns: ['unregistered', 'price'], search: '样例' }))
  localStorage.setItem('broken', '{')
  expect(readPreferences('demo', columns).watched).toEqual(['DEMO-1'])
  expect(readPreferences('demo', columns).columns).toEqual(['price'])
  expect(readPreferences('imported', columns).watched).toEqual([])
  expect(readPreferences('broken', columns).columns).toEqual(['price'])
})
