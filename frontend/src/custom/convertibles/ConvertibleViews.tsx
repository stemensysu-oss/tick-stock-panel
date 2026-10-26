import { useState } from 'react'
import { ArrowLeftRight, FileText, ScatterChart, ExternalLink } from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import type { ConvertibleEvent, ConvertibleItem } from '@/lib/api'
import { COLUMNS, formatColumn, formatNumber, safeSourceUrl, BUTTON } from './columns'

export const EVENT_LABELS: Record<ConvertibleEvent['type'], string> = { call: '强赎', put: '回售', revision: '下修', coupon: '付息', maturity: '到期', announcement: '公告' }
export const PROGRESS_LABELS = { unknown: '资料不足', observing: '观察中', met: '条件达标', not_applicable: '不在适用期' }

export function ConvertibleScatter({ items, onOpen }: { items: ConvertibleItem[]; onOpen: (item: ConvertibleItem) => void }) {
  const [active, setActive] = useState<string | null>(null)
  const rows = items.filter(item => item.bond_price != null && item.conversion_premium_pct != null)
  if (!rows.length) return <EmptyState icon={ScatterChart} title="还没有可绘制的转债" hint="散点图需要转债价格、正股价格与转股价；补充数据后即可比较价格与转股溢价。" />
  const prices = rows.map(item => item.bond_price!)
  const premiums = rows.map(item => item.conversion_premium_pct!)
  const minX = Math.floor(Math.min(...prices) / 10) * 10
  const maxX = Math.max(minX + 20, Math.ceil(Math.max(...prices) / 10) * 10)
  const minY = Math.floor(Math.min(0, ...premiums) / 10) * 10
  const maxY = Math.max(minY + 20, Math.ceil(Math.max(...premiums) / 10) * 10)
  const x = (price: number) => 75 + (price - minX) / (maxX - minX) * 790
  const y = (premium: number) => 365 - (premium - minY) / (maxY - minY) * 310
  const focus = rows.find(item => item.code === active)
  return <div className="p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-semibold">价格 × 转股溢价率</h3><p className="mt-1 text-[11px] text-muted">{rows.length} 只可绘制 · {items.length - rows.length} 只缺少价格 · 点击或按回车查看详情</p></div><span className="text-[11px] text-muted">蓝点：普通观察　橙点：强赎条件达标</span></div>
    <div className="mt-3 overflow-x-auto"><svg viewBox="0 0 920 420" className="w-full min-w-[520px]" role="group" aria-label="可转债价格与溢价率散点图">
      {Array.from({ length: 6 }, (_, i) => { const px = 75 + i * 158; const py = 365 - i * 62; return <g key={i}><line x1="75" y1={py} x2="865" y2={py} stroke="currentColor" opacity="0.1" /><line x1={px} y1="55" x2={px} y2="365" stroke="currentColor" opacity="0.06" /><text x="64" y={py + 4} fill="currentColor" opacity="0.55" textAnchor="end" fontSize="11">{formatNumber(minY + (maxY - minY) * i / 5, 1)}</text><text x={px} y="385" fill="currentColor" opacity="0.55" textAnchor="middle" fontSize="11">{formatNumber(minX + (maxX - minX) * i / 5, 1)}</text></g> })}
      <text x="75" y="30" fill="currentColor" opacity="0.65" fontSize="12">转股溢价率（%）</text><text x="865" y="411" fill="currentColor" opacity="0.65" fontSize="12" textAnchor="end">转债现价（元 / 张）</text>
      {rows.map(item => <circle key={item.code} cx={x(item.bond_price!)} cy={y(item.conversion_premium_pct!)} r={active === item.code ? 7 : 4.5} className={item.call_progress?.state === 'met' ? 'fill-warning' : 'fill-accent'} fillOpacity={active === item.code ? 1 : 0.65} stroke="currentColor" strokeOpacity="0.15" role="button" tabIndex={0} aria-label={`${item.name}，现价 ${formatNumber(item.bond_price)} 元，溢价率 ${formatNumber(item.conversion_premium_pct)}%，查看详情`} onMouseEnter={() => setActive(item.code)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(item.code)} onBlur={() => setActive(null)} onClick={() => onOpen(item)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(item) } }} style={{ cursor: 'pointer' }}><title>{item.name} · {item.code}｜{formatNumber(item.bond_price)} 元｜{formatNumber(item.conversion_premium_pct)}%</title></circle>)}
    </svg></div>
    <div className="min-h-7 text-[11px] text-secondary" aria-live="polite">{focus ? <span>{focus.name} {focus.code}　现价 <b>{formatNumber(focus.bond_price)}</b> 元　溢价 <b>{formatNumber(focus.conversion_premium_pct)}%</b>　双低 <b>{formatNumber(focus.double_low)}</b></span> : '将指针移到点上，或使用 Tab 聚焦数据点查看数值。低价格或低溢价并不等于低风险。'}</div>
  </div>
}

export function ConvertibleComparison({ items, onOpen, onRemove }: { items: ConvertibleItem[]; onOpen: (item: ConvertibleItem) => void; onRemove: (code: string) => void }) {
  if (items.length < 2) return <EmptyState icon={ArrowLeftRight} title="选取 2–4 只转债进行对比" hint="在列表代码左侧勾选转债，再切换到对比。对比保留选择，不随筛选条件变化。" />
  return <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-xs"><caption className="sr-only">可转债逐项对比，纯债和期权为模型值</caption><thead><tr><th className="sticky left-0 z-10 bg-surface px-2 py-2 text-left font-medium text-muted">研究指标</th>{items.map(item => <th className="min-w-28 px-2 py-2 text-left" key={item.code}><button type="button" onClick={() => onOpen(item)} className="text-sm font-semibold hover:text-accent">{item.name}</button><p className="mt-1 font-mono text-[10px] font-normal text-muted">{item.code}</p><button type="button" onClick={() => onRemove(item.code)} className="mt-2 text-[10px] font-normal text-muted hover:text-danger">移出对比</button></th>)}</tr></thead><tbody className="divide-y divide-border/60">{COLUMNS.filter(column => !['code', 'name'].includes(column.id)).map(column => <tr key={column.id}><th title={column.description} className="sticky left-0 bg-surface px-2 py-1.5 text-left font-normal text-secondary">{column.label}{column.unit && ` (${column.unit})`}</th>{items.map(item => <td key={item.code} className="px-2 py-1.5 font-mono tabular-nums">{formatColumn(item, column)}</td>)}</tr>)}</tbody></table></div>
}

export function ConvertibleEvents({ items, kind, onOpen }: { items: ConvertibleItem[]; kind?: ConvertibleEvent['type']; onOpen: (item: ConvertibleItem) => void }) {
  const rows = items.flatMap(item => (item.research?.events ?? []).filter(event => !kind || event.type === kind).map((event, index) => ({ item, event, key: `${item.code}-${index}` }))).sort((a, b) => b.event.date.localeCompare(a.event.date))
  if (!rows.length) return <EmptyState icon={FileText} title={kind ? `没有${EVENT_LABELS[kind]}记录` : '还没有公告记录'} hint="打开任意转债详情，在“公告”中记录已核实的事件日期、内容与来源链接。当前没有自动获取公告。" />
  return <div className="divide-y divide-border/60">{rows.map(({ item, event, key }) => { const url = safeSourceUrl(event.source_url); return <article key={key} className="flex flex-wrap items-start gap-4 p-4 sm:p-5"><time className="w-24 shrink-0 font-mono text-xs text-muted">{event.date}</time><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="rounded bg-elevated px-2 py-0.5 text-[10px] text-secondary">{EVENT_LABELS[event.type]}</span><button type="button" onClick={() => onOpen(item)} className="text-xs font-semibold hover:text-accent">{item.name}</button></div><h3 className="mt-2 break-words text-sm">{event.title}</h3>{event.note && <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-secondary">{event.note}</p>}{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent">核对来源 <ExternalLink className="h-3 w-3" /></a> : <p className="mt-2 text-[10px] text-muted">尚未提供可访问的来源链接</p>}</div><button type="button" className={BUTTON} onClick={() => onOpen(item)}>转债详情</button></article> })}</div>
}

export function ConvertibleClauseTable({ items, kind, onOpen }: { items: ConvertibleItem[]; kind: 'call' | 'put'; onOpen: (item: ConvertibleItem) => void }) {
  if (!items.length) return <EmptyState icon={FileText} title={`尚无${kind === 'call' ? '强赎' : '回售'}资料`} hint="在转债详情中录入条款及交易日观察记录，也可添加已核实的公告。资料不足不会标为未触发。" />
  return <div className="overflow-x-auto"><table className="w-full min-w-[850px] text-xs"><thead className="border-y border-border bg-elevated/40 text-left text-[11px] text-muted"><tr>{['转债', '价格条件状态', '满足 / 所需天数', '已有观察 / 窗口', '触发价（元）', '观察说明', '公告记录'].map(label => <th key={label} className="px-2 py-1.5 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{items.map(item => { const progress = kind === 'call' ? item.call_progress : item.put_progress; const events = item.research?.events.filter(event => event.type === kind) ?? []; return <tr key={item.code}><td className="px-2 py-1.5"><button type="button" onClick={() => onOpen(item)} className="whitespace-nowrap font-medium hover:text-accent">{item.name}</button><p className="mt-1 font-mono text-[10px] text-muted">{item.code}</p></td><td className="whitespace-nowrap px-2 py-1.5"><span className={progress?.state === 'met' ? 'text-warning' : 'text-secondary'}>{progress ? PROGRESS_LABELS[progress.state] : '资料不足'}</span></td><td className="px-2 py-1.5 font-mono">{progress?.hit_days ?? '—'} / {progress?.required_days ?? '—'}</td><td className="px-2 py-1.5 font-mono">{progress?.observed_days ?? '—'} / {progress?.window_days ?? '—'}</td><td className="px-2 py-1.5 font-mono">{formatNumber(kind === 'call' ? item.call_trigger_price : item.put_trigger_price)}</td><td className="max-w-80 px-2 py-1.5 text-[11px] leading-relaxed text-muted">{progress?.note || '尚未提供可验证的观察记录'}</td><td className="px-2 py-1.5"><button type="button" onClick={() => onOpen(item)} className="whitespace-nowrap text-accent hover:underline">{events.length} 条记录</button>{kind === 'call' && item.redemption_status && <p className="mt-1 max-w-40 text-[10px] text-muted">{item.redemption_status}</p>}</td></tr> })}</tbody></table><p className="p-4 text-[11px] leading-relaxed text-muted">价格条件达标并不等于公司已经决定强赎或回售权可以行使；适用期间、余额条件、重置规则及实际安排均需结合公告核对。</p></div>
}
