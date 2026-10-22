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
      <td className="min-w-40 px-4 py-3"><div className="font-medium text-foreground">{row.name}</div><div className="mt-1 flex gap-2 font-mono text-[10px] text-muted"><span>{row.code}</span><span>{row.currency}</span></div><span className={cn('mt-1 inline-block text-[10px]', row.data_status === 'demo' ? 'text-warning' : 'text-muted')}>{row.data_status === 'demo' ? '虚构演示' : row.data_status === 'market' ? '网络数据 · 核对来源时点' : '用户导入 · 未核验'}</span></td>
      {columns.map(column => <td key={column.key} className={cn('max-w-64 px-4 py-3', column.type === 'number' ? 'text-right font-mono tabular-nums' : 'text-secondary')}>{formatCell(row, column)}</td>)}
      <td className="min-w-36 px-4 py-3"><div className="font-mono text-secondary">{row.as_of || '--'}</div>{row.data_status === 'market' && <div className="mt-1 text-[10px] text-muted">{String(row.quote_at || row.data_as_of || '来源未给更新时点')}</div>}<div className="mt-1 max-w-60 break-words text-[10px] text-muted">{row.source_name || '--'}</div></td>
      {onSelect && <td className="px-4 py-3"><button type="button" className="whitespace-nowrap text-accent hover:underline" onClick={() => onSelect(row)} aria-label={`查看 ${row.name} 详情`}>详情</button></td>}
    </tr>)}</tbody>
  </table></div>
}

export function AssetDetail({ category, row, onClose }: { category: MultiAssetCategory; row: MultiAssetRow; onClose: () => void }) {
  const url = safeSourceUrl(row.source_url)
  const fields = [...category.fields, ...category.columns.filter(column => !(category.fields.some(field => field.key === column.key)))]
  return <section aria-label={`${row.name} 研究详情`} className="rounded-card border border-accent/25 bg-surface p-4 sm:p-5">
    <div className="flex items-start justify-between gap-3"><div><h3 className="text-[16px] font-semibold">{row.name}<span className="ml-2 font-mono text-xs font-normal text-muted">{row.code}</span></h3><p className="mt-1 text-xs text-muted">{row.data_status === 'demo' ? '虚构数据，仅用于理解界面与计算方法。' : row.data_status === 'market' ? `网络来源：${row.source_name}；来源时点 ${row.quote_at || row.data_as_of || '来源未给更新时点'}；抓取时点 ${row.fetched_at || '--'}。` : '用户导入资料；来源名称与日期由用户填写，尚未经过 API 核验。'}</p></div><button type="button" onClick={onClose} aria-label="关闭研究详情" className="rounded p-1.5 hover:bg-elevated"><X className="h-4 w-4" /></button></div>
    {row.data_status === 'market' && <NetworkProvenance row={row} />}
    {row.warnings.length > 0 && <ul className="mt-4 list-inside list-disc space-y-1 rounded-btn border border-warning/25 bg-warning/5 p-3 text-xs leading-relaxed text-secondary">{row.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
    <dl className="mt-5 grid grid-cols-2 gap-5 md:grid-cols-3 xl:grid-cols-4">{fields.filter(field => !['source_url', 'code', 'name'].includes(field.key)).map(field => <div key={field.key}><dt className="text-[11px] text-muted">{field.label}</dt><dd className="mt-1 break-words text-sm">{formatCell(row, field)}</dd>{field.description && <p className="mt-1 text-[10px] leading-relaxed text-muted">{field.description}</p>}</div>)}</dl>
    {url && <a href={url} target="_blank" rel="noopener noreferrer" className={`${BUTTON} mt-5 text-accent`}><ExternalLink className="h-3.5 w-3.5" />{row.data_status === 'market' ? '打开数据来源' : '打开用户提供的来源'}</a>}
    {row.source_url && !url && <p className="mt-4 text-xs text-warning">来源链接格式不受支持，未提供可点击链接。</p>}
  </section>
}

function NetworkProvenance({ row }: { row: MultiAssetRow }) {
  const eligibilityUrl = safeSourceUrl(row.eligibility_source_url)
  const fxUrl = safeSourceUrl(row.fx_source_url)
  const facts = [
    ['报价时点', row.quote_at], ['H 股报价时点', row.h_quote_at],
    ['汇率时点', row.fx_quote_at || row.fx_as_of], ['汇率来源', row.fx_source_name],
    ['披露/资料时点', row.data_as_of], ['方案进度', row.progress],
    ['预案公告日', row.plan_notice_date], ['股权登记日', row.equity_record_date],
    ['除息日', row.ex_dividend_date], ['申购代码', row.apply_code],
    ['申购日', row.subscription_date], ['上市日', row.listing_date],
    ['中签/结果日', row.ballot_num_date], ['缴款日', row.ballot_pay_date],
    ['回转资格', row.eligibility_label],
    ['资格目录日期', row.eligibility_as_of], ['交易所分类', row.fund_classification],
  ].filter(([, value]) => typeof value === 'string' && value)
  if (!facts.length && !eligibilityUrl && !fxUrl) return null
  return <div className="mt-4 rounded-btn border border-border bg-elevated/30 p-3" aria-label="网络数据来源与时点">
    <dl className="grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-3">{facts.map(([label, value]) => <div key={String(label)}><dt className="text-muted">{String(label)}</dt><dd className="mt-1 break-words text-secondary">{String(value)}</dd></div>)}</dl>
    {(eligibilityUrl || fxUrl) && <div className="mt-3 flex flex-wrap gap-4 text-xs text-accent">{eligibilityUrl && <a href={eligibilityUrl} target="_blank" rel="noopener noreferrer" className="hover:underline">查看交易所资格依据</a>}{fxUrl && <a href={fxUrl} target="_blank" rel="noopener noreferrer" className="hover:underline">查看汇率来源</a>}</div>}
  </div>
}
