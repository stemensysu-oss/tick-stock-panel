import type { ConvertibleItem } from '@/lib/api'
import type { ColumnId } from './columns'

export type ConvertibleSort = ColumnId
export type SortDirection = 'asc' | 'desc'
export interface ConvertibleFilters {
  search: string
  maxPrice: string
  maxPremium: string
  maxDoubleLow: string
  minPrice?: string
  minYield?: string
  maxSize?: string
  maxYears?: string
  rating?: string
  industry?: string
  assetType?: string
  exchange?: string
}
export const EMPTY_FILTERS: ConvertibleFilters = { search: '', minPrice: '', maxPrice: '', maxPremium: '', maxDoubleLow: '', minYield: '', maxSize: '', maxYears: '', rating: '', industry: '', assetType: '', exchange: '' }

function threshold(value: number | null | undefined, input: string | undefined, direction: 'above' | 'below', divisor = 1): boolean {
  if (!input?.trim()) return true
  const limit = Number(input)
  return Number.isFinite(limit) && value != null && Number.isFinite(value)
    && (direction === 'below' ? value / divisor <= limit : value / divisor >= limit)
}
export function filterConvertibles(rows: ConvertibleItem[], filters: ConvertibleFilters): ConvertibleItem[] {
  const query = filters.search.trim().toLowerCase()
  return rows.filter(row => (
    (!query || [row.code, row.name, row.stock_code, row.stock_name, row.industry, row.concepts].some(value => value?.toLowerCase().includes(query)))
    && threshold(row.bond_price, filters.minPrice, 'above')
    && threshold(row.bond_price, filters.maxPrice, 'below')
    && threshold(row.conversion_premium_pct, filters.maxPremium, 'below')
    && threshold(row.double_low, filters.maxDoubleLow, 'below')
    && threshold(row.ytm_pct, filters.minYield, 'above')
    && threshold(row.outstanding_amount, filters.maxSize, 'below', 100_000_000)
    && threshold(row.remaining_years, filters.maxYears, 'below')
    && (!filters.rating || row.credit_rating === filters.rating)
    && (!filters.industry || row.industry === filters.industry)
    && (!filters.assetType || row.asset_type === filters.assetType)
    && (!filters.exchange || row.code.endsWith(`.${filters.exchange}`))
  ))
}
export function sortConvertibles(rows: ConvertibleItem[], field: ConvertibleSort, direction: SortDirection): ConvertibleItem[] {
  return [...rows].sort((left, right) => {
    const a = left[field]
    const b = right[field]
    if (a == null && b == null) return left.code.localeCompare(right.code)
    if (a == null) return 1
    if (b == null) return -1
    const comparison = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'zh-CN')
    return comparison === 0 ? left.code.localeCompare(right.code) : comparison * (direction === 'asc' ? 1 : -1)
  })
}
