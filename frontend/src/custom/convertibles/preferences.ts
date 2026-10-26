import { useState } from 'react'
import { COLUMNS, DEFAULT_COLUMNS, type ColumnId } from './columns'

const KEY = 'tsp.convertibles.preferences.v1'
export interface ResearchPreferences { watched: string[]; hidden: string[]; columns: ColumnId[] }
const DEFAULT: ResearchPreferences = { watched: [], hidden: [], columns: DEFAULT_COLUMNS }
export const codeIdentity = (code: string): string => code.split('.')[0]
const validCode = (value: unknown): value is string => typeof value === 'string' && /^[0-9]{6}(\.(SH|SZ|BJ))?$/.test(value)
export function readPreferences(): ResearchPreferences {
  try {
    const raw: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? 'null')
    if (!raw || typeof raw !== 'object') return DEFAULT
    const candidate = raw as Record<string, unknown>
    const codes = (value: unknown) => Array.isArray(value) ? [...new Set(value.filter(validCode).map(codeIdentity))].slice(0, 2000) : []
    const rawColumns = candidate.columns
    const oldDefault = ['code', 'name', 'bond_price', 'bond_change_pct', 'stock_name', 'stock_price', 'conversion_price', 'conversion_value', 'conversion_premium_pct', 'double_low', 'credit_rating', 'maturity_date', 'outstanding_amount', 'ytm_pct']
    const legacyDefault = Array.isArray(rawColumns) && rawColumns.length === oldDefault.length && oldDefault.every(id => rawColumns.includes(id))
    const columns = legacyDefault ? DEFAULT_COLUMNS : Array.isArray(rawColumns) ? COLUMNS.filter(column => rawColumns.includes(column.id)).map(column => column.id) : DEFAULT_COLUMNS
    return { watched: codes(candidate.watched), hidden: codes(candidate.hidden), columns: [...new Set<ColumnId>(['code', 'name', ...columns])] }
  } catch { return DEFAULT }
}
export function useResearchPreferences() {
  const [preferences, setPreferences] = useState(readPreferences)
  const [storageWarning, setStorageWarning] = useState('')
  const update = (next: ResearchPreferences) => {
    setPreferences(next)
    try { window.localStorage.setItem(KEY, JSON.stringify(next)); setStorageWarning('') }
    catch { setStorageWarning('浏览器暂不允许保存偏好；本次自选、排除和列设置只在当前页面有效。') }
  }
  const toggle = (key: 'watched' | 'hidden', code: string) => {
    const identity = codeIdentity(code)
    update({ ...preferences, [key]: preferences[key].includes(identity) ? preferences[key].filter(value => value !== identity) : [...preferences[key], identity] })
  }
  return { preferences, update, toggle, storageWarning }
}
