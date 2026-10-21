import { ArrowDown, ArrowUp, Star } from 'lucide-react'
import type { ConvertibleItem } from '@/lib/api'
import { cn } from '@/lib/cn'
import { COLUMNS, DEFAULT_COLUMNS, formatColumn, type ColumnId } from './columns'
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
  return (
    <div className="max-w-full overflow-x-auto overscroll-x-contain">
      <table className="w-full text-xs" style={{ minWidth: Math.max(750, visible.length * 106) }}>
        <caption className="sr-only">{caption}；价格单位元，百分比为百分数；缺失数据以横线显示；纯债和期权为模型值</caption>
        <thead className="border-y border-border bg-elevated/50 text-right text-[11px] text-muted"><tr>
          {visible.map(column => <th key={column.id} className={cn('whitespace-nowrap px-3 py-3 font-medium', column.id === 'code' && 'sticky left-0 z-20 w-[130px] min-w-[130px] bg-surface text-left', column.id === 'name' && 'sticky left-[130px] z-20 min-w-[130px] bg-surface text-left')} aria-sort={sort === column.id ? direction === 'asc' ? 'ascending' : 'descending' : undefined}>
            {onSort ? <button type="button" onClick={() => onSort(column.id)} title={column.description} className={cn('inline-flex items-center gap-1 hover:text-accent', sort === column.id && 'text-accent')}><span>{column.label}{column.unit && <span className="ml-1 opacity-65">({column.unit})</span>}</span>{sort === column.id && (direction === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}</button> : <span title={column.description}>{column.label}{column.unit && ` (${column.unit})`}</span>}
          </th>)}
        </tr></thead>
        <tbody className="divide-y divide-border/60">{items.map(item => <tr key={item.code} className="group text-right hover:bg-elevated/30">
          {visible.map(column => {
            const value = item[column.id]
            return <td key={column.id} title={column.description} className={cn('whitespace-nowrap px-3 py-3 font-mono tabular-nums', column.id === 'code' && 'sticky left-0 z-10 bg-surface text-left group-hover:bg-elevated', column.id === 'name' && 'sticky left-[130px] z-10 bg-surface text-left font-sans group-hover:bg-elevated', column.id === 'double_low' && 'font-semibold text-accent', (column.id === 'bond_change_pct' || column.id === 'stock_change_pct') && typeof value === 'number' && (value > 0 ? 'text-danger' : value < 0 ? 'text-bear' : 'text-secondary'), value == null && 'text-muted')}>
              {column.id === 'code' ? <div className="flex items-center gap-2">{onCompare && <input type="checkbox" checked={selected.includes(codeIdentity(item.code))} onChange={() => onCompare(item.code)} aria-label={`对比 ${item.name}`} className="h-3.5 w-3.5 shrink-0 accent-accent" />}{onWatch && <button type="button" onClick={() => onWatch(item.code)} aria-label={`${watched.includes(codeIdentity(item.code)) ? '取消自选' : '加入自选'} ${item.name}`} aria-pressed={watched.includes(codeIdentity(item.code))} className="rounded p-0.5 text-muted hover:text-warning"><Star className={cn('h-3.5 w-3.5', watched.includes(codeIdentity(item.code)) && 'fill-warning text-warning')} /></button>}<span className="text-[10px]">{item.code}</span></div>
                : column.id === 'name' ? <div>{onOpen ? <button type="button" onClick={() => onOpen(item)} className="max-w-40 truncate text-left font-medium hover:text-accent hover:underline">{item.name}</button> : item.name}<div className="mt-1 max-w-40 truncate text-[10px] font-normal text-muted">{item.call_progress?.state === 'met' ? <span className="text-warning">强赎条件达标 · 待核公告</span> : item.industry || item.redemption_status || (item.asset_type === 'exchangeable' ? '可交换债' : '可转债')}</div></div>
                : formatColumn(item, column)}
            </td>
          })}
        </tr>)}</tbody>
      </table>
    </div>
  )
}
