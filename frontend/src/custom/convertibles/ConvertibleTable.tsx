import { ArrowDown, ArrowUp, Star } from 'lucide-react'
import type { ConvertibleItem } from '@/lib/api'
import { cn } from '@/lib/cn'
import { COLUMNS, DEFAULT_COLUMNS, formatColumn, type ColumnId } from './columns'
import { referenceHint } from './reference'
import type { ConvertibleSort, SortDirection } from './filter'
import { codeIdentity } from './preferences'

interface Props {
  items: ConvertibleItem[]
  caption: string
  columns?: ColumnId[]
  sort?: ConvertibleSort
  direction?: SortDirection
  onSort?: (column: ConvertibleSort) => void
  watched?: string[]
  selected?: string[]
  onWatch?: (code: string) => void
  onCompare?: (code: string) => void
  onOpen?: (item: ConvertibleItem) => void
}
export function ConvertibleTable({ items, caption, columns = DEFAULT_COLUMNS, sort, direction, onSort, watched = [], selected = [], onWatch, onCompare, onOpen }: Props) {
  const visible = COLUMNS.filter(column => columns.includes(column.id))
  const widths: Partial<Record<ColumnId, number>> = { code: 108, name: 100, stock_name: 92, stock_code: 90, maturity_date: 98, pure_bond_value_date: 98, pure_bond_value_basis: 96, credit_rating: 60, turnover_amount: 94, ytm_pct: 88, put_yield_pct: 88 }
  const width = (id: ColumnId) => widths[id] ?? 78
  const scaled = (size: number) => `calc(${size}px * var(--content-font-scale, 1))`
  const sticky = (id: ColumnId) => id === 'code' || id === 'name' ? { left: id === 'code' ? 0 : scaled(columns.includes('code') ? width('code') : 0) } : undefined
  return (
    <div className="max-w-full overflow-x-auto overscroll-x-contain">
      <table aria-label="紧凑可转债研究表" className="table-fixed text-xs" style={{ width: scaled(visible.reduce((sum, column) => sum + width(column.id), 0)) }}><colgroup>{visible.map(column => <col key={column.id} style={{ width: scaled(width(column.id)) }} />)}</colgroup>
        <caption className="sr-only">{caption}；价格单位元，百分比为百分数；缺失数据以横线显示；纯债和期权为模型值</caption>
        <thead className="border-y border-border bg-elevated/50 text-right text-[11px] text-muted"><tr>
          {visible.map(column => <th key={column.id} style={{ ...sticky(column.id), lineHeight: 1.25 }} className={cn('px-1.5 py-2 align-middle font-medium', sticky(column.id) && 'sticky z-20 bg-surface text-left')} aria-sort={sort === column.id ? direction === 'asc' ? 'ascending' : 'descending' : undefined}>
            {onSort ? <button type="button" onClick={() => onSort(column.id)} title={column.description} className={cn('inline-flex max-w-full items-center gap-0.5 hover:text-accent', sort === column.id && 'text-accent')}><span className="whitespace-normal break-words">{column.label}{column.unit && <span className="ml-1 opacity-65">({column.unit})</span>}</span>{sort === column.id && (direction === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}</button> : <span title={column.description}>{column.label}{column.unit && ` (${column.unit})`}</span>}
          </th>)}
        </tr></thead>
        <tbody className="divide-y divide-border/60">{items.map(item => <tr key={item.code} className="group text-right hover:bg-elevated/30">
          {visible.map(column => {
            const value = item[column.id]
            const status = item.call_progress?.state === 'met' ? '强赎条件达标 · 待核公告' : item.industry || item.redemption_status || (item.asset_type === 'exchangeable' ? '可交换债' : '可转债')
            const hint = column.id === 'name' ? `${item.name} · ${status}` : column.id === 'code' ? item.code : value == null ? column.description : `${value}${column.description ? ` · ${column.description}` : ''}`
            return <td key={column.id} title={column.id === 'pure_bond_value' ? referenceHint(item) ?? column.description : hint} style={{ ...sticky(column.id), lineHeight: 1.25 }} className={cn('overflow-hidden whitespace-nowrap px-1.5 py-1.5 font-mono tabular-nums', column.id === 'code' && 'sticky z-10 bg-surface text-left group-hover:bg-elevated', column.id === 'name' && 'sticky z-10 bg-surface text-left font-sans group-hover:bg-elevated', column.id === 'double_low' && 'font-semibold text-accent', (column.id === 'bond_change_pct' || column.id === 'stock_change_pct') && typeof value === 'number' && (value > 0 ? 'text-danger' : value < 0 ? 'text-bear' : 'text-secondary'), value == null && 'text-muted')}>
              {column.id === 'code' ? <div className="flex items-center gap-1.5">{onCompare && <input type="checkbox" checked={selected.includes(codeIdentity(item.code))} onChange={() => onCompare(item.code)} aria-label={`对比 ${item.name}`} className="h-3.5 w-3.5 shrink-0 accent-accent" />}{onWatch && <button type="button" onClick={() => onWatch(item.code)} aria-label={`${watched.includes(codeIdentity(item.code)) ? '取消自选' : '加入自选'} ${item.name}`} aria-pressed={watched.includes(codeIdentity(item.code))} className="shrink-0 rounded text-muted hover:text-warning"><Star className={cn('h-3.5 w-3.5', watched.includes(codeIdentity(item.code)) && 'fill-warning text-warning')} /></button>}<span title={item.code} className="truncate text-[10px]">{codeIdentity(item.code)}</span></div>
                : column.id === 'name' ? <div>{onOpen ? <button type="button" onClick={() => onOpen(item)} className={cn('block w-full truncate text-left font-medium hover:text-accent hover:underline', item.call_progress?.state === 'met' && 'text-warning')}>{item.name}</button> : item.name}</div>
                : <span className="block truncate">{formatColumn(item, column)}</span>}
            </td>
          })}
        </tr>)}</tbody>
      </table>
    </div>
  )
}
