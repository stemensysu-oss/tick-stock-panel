// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { readPreferences } from './preferences'
import { DEFAULT_COLUMNS } from './columns'

afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear() })
it('浏览器禁用存储时仍能读取默认偏好，不阻断工作台', () => {
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new DOMException('denied', 'SecurityError') })
  expect(readPreferences()).toEqual({ watched: [], hidden: [], columns: DEFAULT_COLUMNS })
})
it('旧偏好和非法列不会污染新工作台，代码和名称始终保留', () => {
  window.localStorage.setItem('tsp.convertibles.preferences.v1', JSON.stringify({ watched: ['123001.SZ', '123001.SZ', '<script>'], hidden: null, columns: ['bond_price', 'fake_key'] }))
  expect(readPreferences()).toEqual({ watched: ['123001'], hidden: [], columns: ['code', 'name', 'bond_price'] })
})

it('CSV补充交易所后缀后自选/排除仍按同一六位身份匹配', () => {
  window.localStorage.setItem('tsp.convertibles.preferences.v1', JSON.stringify({ watched: ['110001.SH', '110001'], hidden: ['123001.SZ', '123001'], columns: [] }))
  expect(readPreferences().watched).toEqual(['110001'])
  expect(readPreferences().hidden).toEqual(['123001'])
})
