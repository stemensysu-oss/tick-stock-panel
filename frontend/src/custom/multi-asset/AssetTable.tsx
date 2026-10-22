import { ExternalLink, Star, X } from 'lucide-react'
import type { MultiAssetCategory, MultiAssetColumn, MultiAssetRow } from '@/lib/api'
import { cn } from '@/lib/cn'
import { BUTTON, formatCell, safeSourceUrl } from './model'

const FIXED_COLUMNS = new Set(['code', 'name', 'currency', 'as_of', 'source_name'])
export const researchColumns = (category: MultiAssetCategory) => category.columns.filter(column => !FIXED_COLUMNS.has(column.key))

export function AssetTable({ rows, columns, watched = [], onWatch, onSelect, caption }: {
  rows: MultiAssetRow[]; columns: MultiAssetColumn[]; watched?: string[]
  onWatch?: (code: string) => void; onSelect?: (row: MultiAssetRow) => void; caption: string
}) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs">
    <caption className="sr-only">{caption}；缺失值显示 --，百分比按百分数显示</caption>
    <thead className="border-y border-border bg-elevated/50 text-[11px] text-muted"><tr>
      {onWatch && <th className="w-10 px-3 py-3 font-medium"><span className="sr-only">自选</span></th>}
      <th className="px-4 py-3 font-medium">标的 / 币种</th>
      {columns.map(column => <th key={column.key} title={column.description || undefined} className={cn('whitespace-nowrap px-4 py-3 font-medium', column.type === 'number' && 'text-right')}>{column.label}{column.unit && column.unit !== '%' ? `（${column.unit}）` : ''}</th>)}
      <th className="px-4 py-3 font-medium">资料基准日 / 来源</th>
      {onSelect && <th className="w-16 px-4 py-3 font-medium">研究</th>}
    </tr></thead>
    <tbody className="divide-y divide-border/60">{rows.map(row => <tr key={row.code} className="hover:bg-elevated/30">
      {onWatch && <td className="px-3 py-3"><button type="button" onClick={() => onWatch(row.code)} aria-label={`${watched.includes(row.code) ? '移出' : '加入'}自选 ${row.name}`} aria-pressed={watched.includes(row.code)} className="rounded p-1.5 hover:bg-elevated"><Star className={cn('h-3.5 w-3.5', watched.includes(row.code) ? 'fill-warning/30 text-warning' : 'text-muted')} /></button></td>}
      <td className="min-w-40 px-4 py-3"><div className="font-medium text-foreground">{row.name}</div><div className="mt-1 flex gap-2 font-mono text-[10px] text-muted"><span>{row.code}</span><span>{row.currency}</span></div><span className={cn('mt-1 inline-block text-[10px]', row.data_status === 'demo' ? 'text-warning' : 'text-muted')}>{row.data_status === 'demo' ? '虚构演示' : row.data_status === 'market' ? '网络行情 · 核对来源时点' : '用户导入 · 未核验'}</span></td>
      {columns.map(column => <td key={column.key} className={cn('max-w-64 px-4 py-3', column.type === 'number' ? 'text-right font-mono tabular-nums' : 'text-secondary')}>{formatCell(row, column)}</td>)}
      <td className="min-w-36 px-4 py-3"><div className="font-mono text-secondary">{row.as_of || '--'}</div>{row.data_status === 'market' && <div className="mt-1 text-[10px] text-muted">{String(row.quote_at || '--')}</div>}<div className="mt-1 max-w-60 break-words text-[10px] text-muted">{row.source_name || '--'}</div></td>
      {onSelect && <td className="px-4 py-3"><button type="button" className="whitespace-nowrap text-accent hover:underline" onClick={() => onSelect(row)} aria-label={`查看 ${row.name} 详情`}>详情</button></td>}
    </tr>)}</tbody>
  </table></div>
}

export function AssetDetail({ category, row, onClose }: { category: MultiAssetCategory; row: MultiAssetRow; onClose: () => void }) {
  const url = safeSourceUrl(row.source_url)
  const fields = [...category.fields, ...category.columns.filter(column => !(category.fields.some(field => field.key === column.key)))]
  return <section aria-label={`${row.name} 研究详情`} className="rounded-card border border-accent/25 bg-surface p-4 sm:p-5">
    <div className="flex items-start justify-between gap-3"><div><h3 className="text-[16px] font-semibold">{row.name}<span className="ml-2 font-mono text-xs font-normal text-muted">{row.code}</span></h3><p className="mt-1 text-xs text-muted">{row.data_status === 'demo' ? '虚构数据，仅用于理解界面与计算方法。' : row.data_status === 'market' ? `网络来源：${row.source_name}；来源时点 ${row.quote_at || '--'}；抓取时点 ${row.fetched_at || '--'}。` : '用户导入资料；来源名称与日期由用户填写，尚未经过 API 核验。'}</p></div><button type="button" onClick={onClose} aria-label="关闭研究详情" className="rounded p-1.5 hover:bg-elevated"><X className="h-4 w-4" /></button></div>
    {row.warnings.length > 0 && <ul className="mt-4 list-inside list-disc space-y-1 rounded-btn border border-warning/25 bg-warning/5 p-3 text-xs leading-relaxed text-secondary">{row.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
    <dl className="mt-5 grid grid-cols-2 gap-5 md:grid-cols-3 xl:grid-cols-4">{fields.filter(field => !['source_url', 'code', 'name'].includes(field.key)).map(field => <div key={field.key}><dt className="text-[11px] text-muted">{field.label}</dt><dd className="mt-1 break-words text-sm">{formatCell(row, field)}</dd>{field.description && <p className="mt-1 text-[10px] leading-relaxed text-muted">{field.description}</p>}</div>)}</dl>
    {url && <a href={url} target="_blank" rel="noopener noreferrer" className={`${BUTTON} mt-5 text-accent`}><ExternalLink className="h-3.5 w-3.5" />{row.data_status === 'market' ? '打开行情来源' : '打开用户提供的来源'}</a>}
    {row.source_url && !url && <p className="mt-4 text-xs text-warning">来源链接格式不受支持，未提供可点击链接。</p>}
  </section>
}
