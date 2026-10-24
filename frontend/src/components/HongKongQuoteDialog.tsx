import { marketLabel } from '@/lib/hongKong'
import { X } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { fmtPct, fmtPrice, priceColorClass } from '@/lib/format'
import type { WatchlistHkQuote } from '@/lib/api'

const SOURCES: Record<string, string> = { tickflow: 'TickFlow', fuyao: '扶摇', tencent_public: '腾讯公开补充行情', eastmoney_public: '东方财富公开补充行情' }

export function HongKongQuoteDialog({ symbol, name, row, onClose, onAdd, adding, inWatchlist, onRefresh, refreshing, error }: {
  symbol: string; name: string; row?: Partial<WatchlistHkQuote>; onClose: () => void
  onAdd: () => void; adding: boolean; inWatchlist: boolean
  onRefresh: () => void; refreshing: boolean; error?: string
}) {
  const currencyConfirmed = ['HKD','USD','JPY'].includes(row?.currency || '')
  const label = marketLabel(symbol)
  const currency = row?.currency || '币种待确认'
  return <Modal onClose={onClose} ariaLabel={`${name || symbol} ${label}行情`} panelClassName="content-typography w-[94vw] max-w-xl max-h-[90vh] overflow-y-auto rounded-card border border-border bg-surface p-5 shadow-xl">
    <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{row?.name || name || symbol}</h2><p className="mt-1 font-mono text-xs text-muted">{symbol} · {label} · {currencyConfirmed ? currency : '币种待报价确认'}</p></div><button type="button" onClick={onClose} aria-label="关闭市场行情" className="rounded p-1 text-muted hover:bg-elevated"><X className="h-4 w-4" /></button></div>
    <div className="my-5 grid grid-cols-2 gap-4"><div><p className="text-xs text-muted">价格快照（{currencyConfirmed ? currency : '币种待确认'}）</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${priceColorClass(row?.change_pct)}`}>{fmtPrice(row?.close)}</p></div><div><p className="text-xs text-muted">涨跌幅</p><p className={`mt-1 text-xl tabular-nums ${priceColorClass(row?.change_pct)}`}>{fmtPct(row?.change_pct)}</p></div></div>
    <dl className="space-y-3 rounded-btn bg-elevated/40 p-3 text-xs"><div><dt className="text-muted">报价时点</dt><dd className="mt-1 break-words">{row?.quote_at || '尚无有效报价时点'}</dd></div><div><dt className="text-muted">实际行情来源</dt><dd className="mt-1">{row?.quote_source ? SOURCES[row.quote_source] || row.quote_source : '尚未取得有效来源'}</dd></div></dl>
    {error && <p role="alert" className="mt-3 text-xs text-warning">刷新未成功，保留上次有效报价：{error}</p>}
    {row?.quote_warnings?.map((warning, index) => <p key={index} className="mt-2 text-xs text-warning">{warning}</p>)}
    <p className="mt-4 text-xs leading-relaxed text-secondary">行情可能延迟，美日快照可能仅为历史收盘，请核对来源时点。本页仅提供行情快照，币种以有效来源确认为准；日K和关键价位请在“个股分析”查询同一代码；未接入的分时、财务及新闻保持未知。报价不代表账户具备相应市场交易权限。</p>
    {!inWatchlist && <p className="mt-2 text-xs text-muted">加入自选后获取此证券数据，代码保留完整市场标识。</p>}
    <div className="mt-5 flex flex-wrap justify-end gap-2">{!inWatchlist ? <button type="button" disabled={adding} onClick={onAdd} className="rounded-btn bg-accent px-3 py-2 text-xs text-white disabled:opacity-50">{adding ? '正在加入…' : '加入当前自选分组并获取报价'}</button> : <button type="button" disabled={refreshing} onClick={onRefresh} className="rounded-btn border border-border px-3 py-2 text-xs hover:bg-elevated disabled:opacity-50">{refreshing ? '正在刷新…' : '刷新市场数据'}</button>}</div>
  </Modal>
}
