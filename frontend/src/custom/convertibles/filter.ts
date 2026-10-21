import type { ConvertibleItem } from '@/lib/api'

export type ConvertibleSort = 'double_low' | 'bond_price' | 'conversion_premium_pct' | 'maturity_date'
export type SortDirection = 'asc' | 'desc'
export interface ConvertibleFilters {
  search: string
  maxPrice: string
  maxPremium: string
  maxDoubleLow: string
}

function below(value: number | null, input: string): boolean {
  if (input.trim() === '') return true
  const threshold = Number(input)
  return Number.isFinite(threshold) && value !== null && value <= threshold
}

export function filterConvertibles(rows: ConvertibleItem[], filters: ConvertibleFilters): ConvertibleItem[] {
  const query = filters.search.trim().toLowerCase()
  return rows.filter(row => (
    (!query || [row.code, row.name, row.stock_code, row.stock_name].some(value => value?.toLowerCase().includes(query)))
    && below(row.bond_price, filters.maxPrice)
    && below(row.conversion_premium_pct, filters.maxPremium)
    && below(row.double_low, filters.maxDoubleLow)
  ))
}

export function sortConvertibles(rows: ConvertibleItem[], field: ConvertibleSort, direction: SortDirection): ConvertibleItem[] {
  return [...rows].sort((left, right) => {
    const a = left[field]
    const b = right[field]
    if (a === null && b === null) return left.code.localeCompare(right.code)
    if (a === null) return 1
    if (b === null) return -1
    const comparison = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
    return comparison === 0 ? left.code.localeCompare(right.code) : comparison * (direction === 'asc' ? 1 : -1)
  })
}
