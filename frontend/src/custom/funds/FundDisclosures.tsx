import { useQuery } from '@tanstack/react-query'
import { api, type FundLimit } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ErrorState } from '@/components/ErrorState'
import { SourceTrail } from '../SourceTrail'

function formatLimit(limit: FundLimit) {
  if (limit.status === 'unlimited') return '无限额（源明确披露）'
  if (limit.status === 'unknown' || limit.value == null) return '未知'
  return `${limit.value.toLocaleString('zh-CN')} ${limit.unit === 'CNY' ? '元' : '份'}`
}

export function FundDisclosures({ ticker }: { ticker: string }) {
  const trading = useQuery({ queryKey: QK.fundTrading(ticker), queryFn: () => api.fundTrading(ticker), staleTime: 300_000, retry: false })
  const dividends = useQuery({ queryKey: QK.fundDividends(ticker), queryFn: () => api.fundDividends(ticker), staleTime: 300_000, retry: false })
  return <>
    <section aria-label="申赎与限额" className="rounded-card border border-border bg-surface">
      <h2 className="p-4 text-sm font-semibold">申赎与限额</h2>
      {trading.isPending ? <p role="status" className="p-4 text-xs text-muted">正在读取申赎规则…</p> : trading.isError ? <ErrorState title="申赎规则暂不可用" hint={trading.error.message} onRetry={() => void trading.refetch()} /> : trading.data && <>
        <dl className="grid grid-cols-2 gap-5 px-4 pb-5 sm:grid-cols-3">{[
          ['申购状态', trading.data.subscription_status ?? '未知'], ['赎回状态', trading.data.redemption_status ?? '未知'],
          ['最低申购', formatLimit(trading.data.minimum_purchase)], ['日累计申购上限', formatLimit(trading.data.daily_purchase_limit)],
          ['最小赎回份额', formatLimit(trading.data.minimum_redemption)], ['赎回后最低保留', formatLimit(trading.data.minimum_remaining)],
        ].map(([label, value]) => <div key={label}><dt className="text-[11px] text-muted">{label}</dt><dd className="mt-2 text-sm">{value}</dd></div>)}</dl>
        <a href={trading.data.source_url} target="_blank" rel="noopener noreferrer" className="block px-4 pb-3 text-xs text-accent">核对渠道规则原页 →</a>
      </>}
      <SourceTrail data={trading.data} />
    </section>
    <section aria-label="基金分红" className="overflow-hidden rounded-card border border-border bg-surface">
      <h2 className="p-4 text-sm font-semibold">基金分红 · 每10份现金（税前）</h2>
      {dividends.isPending ? <p role="status" className="p-4 text-xs text-muted">正在读取分红记录…</p> : dividends.isError ? <ErrorState title="分红记录暂不可用" hint={dividends.error.message} onRetry={() => void dividends.refetch()} /> : !dividends.data?.items.length ? <p className="px-4 pb-4 text-xs text-muted">源未返回分红记录，不据此判定从未分红。</p> : <div className="max-h-80 overflow-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead className="sticky top-0 bg-elevated"><tr>{['每10份（元）', '权益登记日', '除息日', '发放日', '公告日', '进度'].map(label => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{dividends.data.items.map((item, i) => <tr key={i} className="border-t border-border"><td className="px-4 py-3 font-mono">{item.per_ten_cash_before_tax?.toFixed(4) ?? '—'}</td>{[item.registration_date, item.ex_dividend_date, item.payment_date, item.publish_date, item.progress].map((value, j) => <td key={j} className="px-4 py-3">{value ?? '—'}</td>)}</tr>)}</tbody></table></div>}
      <SourceTrail data={dividends.data} />
    </section>
  </>
}
