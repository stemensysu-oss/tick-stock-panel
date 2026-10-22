import { useState } from 'react'
import type { MultiAssetColumn, MultiAssetMode, MultiAssetRow } from '@/lib/api'

export const BUTTON = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border px-3 py-2 text-xs font-medium transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40'
export const PRIMARY_BUTTON = `${BUTTON} border-accent/30 bg-accent text-white hover:bg-accent/90`
export const INPUT = 'rounded-input border border-border bg-base px-3 py-2 text-sm outline-none focus:border-accent disabled:opacity-50'
export function valueOf(row: MultiAssetRow, key: string): string | number | null {
  const value = key in row.metrics ? row.metrics[key] : row[key]
  return typeof value === 'string' || typeof value === 'number' ? value : null
}
export function formatCell(row: MultiAssetRow, column: MultiAssetColumn): string {
  const value = valueOf(row, column.key)
  if (value === null || value === '') return '--'
  if (typeof value === 'number') return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}${column.unit === '%' ? '%' : ''}`
  return value
}
export function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null } catch { return null }
}
export function saveCsv(text: string, name: string) {
  const url = URL.createObjectURL(new Blob(['\uFEFF', text.replace(/^\uFEFF/, '')], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = name
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export interface Preferences { search: string; watchOnly: boolean; watched: string[]; columns: string[]; sortKey: string; descending: boolean }
export function readPreferences(key: string, columns: MultiAssetColumn[]): Preferences {
  const base: Preferences = { search: '', watchOnly: false, watched: [], columns: columns.map(column => column.key), sortKey: '', descending: false }
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    if (!value || typeof value !== 'object') return base
    const raw = value as Partial<Preferences>
    const strings = (candidate: unknown): string[] => Array.isArray(candidate) ? candidate.filter((item): item is string => typeof item === 'string').slice(0, 2000) : []
    return { search: typeof raw.search === 'string' ? raw.search.slice(0, 200) : '', watchOnly: raw.watchOnly === true,
      watched: strings(raw.watched), columns: Array.isArray(raw.columns) ? columns.filter(column => strings(raw.columns).includes(column.key)).map(column => column.key) : base.columns,
      sortKey: columns.some(column => column.key === raw.sortKey) ? raw.sortKey! : '', descending: raw.descending === true }
  } catch { return base }
}
// Parent keys the category component by both category and mode, so preference state cannot bleed across views.
export function useWorkspacePreferences(category: string, mode: MultiAssetMode, columns: MultiAssetColumn[]) {
  const key = `tsp.multi-asset.v1.${category}.${mode}`
  const [preferences, setPreferences] = useState(() => readPreferences(key, columns))
  const [storageWarning, setStorageWarning] = useState('')
  function update(next: Preferences) {
    setPreferences(next)
    try { localStorage.setItem(key, JSON.stringify(next)); setStorageWarning('') }
    catch { setStorageWarning('当前浏览器无法保存偏好；自选与筛选仅在本次页面中有效。') }
  }
  return { preferences, update, storageWarning }
}
export function filterRows(rows: MultiAssetRow[], preferences: Preferences): MultiAssetRow[] {
  const query = preferences.search.trim().toLocaleLowerCase()
  return rows.filter(row => (!preferences.watchOnly || preferences.watched.includes(row.code)) && (!query || `${row.code} ${row.name} ${row.source_name}`.toLocaleLowerCase().includes(query))).sort((a, b) => {
    if (!preferences.sortKey) return 0
    const left = valueOf(a, preferences.sortKey); const right = valueOf(b, preferences.sortKey)
    if (left === null || left === '') return right === null || right === '' ? 0 : 1
    if (right === null || right === '') return -1
    const result = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), 'zh-CN')
    return preferences.descending ? -result : result
  })
}
