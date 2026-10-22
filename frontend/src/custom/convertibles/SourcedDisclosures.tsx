import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ErrorState } from '@/components/ErrorState'
import { SourceTrail } from '../SourceTrail'
import { BUTTON } from './columns'

const LIFE = { listed: '已上市（公开资料）', terminated: '已终止 / 退市', not_yet_listed: '尚未上市', unknown: '生命周期未知' }
const CALL = { implementation_disclosed: '源披露赎回实施安排，需核对公告', historical_implementation: '历史赎回实施记录', unknown: '未确认实施状态' }
export function SourcedDisclosures({ code }: { code: string }) {
  const query = useQuery({ queryKey: QK.convertibleDisclosures(code), queryFn: () => api.convertibleDisclosures(code), staleTime: 300_000, retry: false })
  const data = query.data
  return <section aria-label="联网条款与强赎资料" aria-busy={query.isFetching} className="space-y-4">
    <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">联网条款与强赎资料</h3><button type="button" disabled={query.isFetching} onClick={() => void query.refetch()} className={BUTTON}><RefreshCw className="h-3.5 w-3.5" />重新读取</button></div>
    <p className="text-xs leading-relaxed text-muted">优先原有API的已实现能力；完整条款与强赎安排目前由公开资料补充，缓存最多5分钟。与手工研究独立保存，未自动确认观察条件或现金流。</p>
    {query.isError && data && <p role="alert" className="rounded-card border border-danger/25 bg-danger/5 p-3 text-xs text-danger">刷新失败，保留上次结果：{query.error.message}</p>}
    {query.isPending ? <p role="status" className="py-8 text-center text-sm text-muted">正在核对条款与实施安排…</p> : query.isError && !data ? <ErrorState title="联网资料暂不可用" hint={query.error.message} onRetry={() => void query.refetch()} retrying={query.isFetching} /> : data && <>
      <p className="rounded-card border border-warning/25 bg-warning/5 p-3 text-xs">{LIFE[data.lifecycle]} · {CALL[data.call_state]}</p>
      <dl className="grid grid-cols-2 gap-4 text-xs">{[
        ['上市日期', data.listing_date], ['退市日期', data.delisting_date], ['源结束日期（非原合同到期保证）', data.source_end_date],
        ['起息日', data.interest_start_date], ['转股开始', data.conversion_start_date], ['转股结束', data.conversion_end_date],
        ['参考转股价（元，生效日未提供）', data.reference_conversion_price], ['面值（元）', data.par_value], ['评级', data.rating], ['评级机构', data.rating_agency],
        ['赎回公告日期', data.call_notice_date], ['赎回登记日', data.call_record_date], ['赎回执行日', data.call_execution_date], ['赎回价（元/张）', data.call_price],
        ['回售公告日', data.put_notice_date], ['回售申报起始', data.put_execution_start], ['回售申报截止', data.put_execution_end], ['回售价（元/张）', data.put_price],
      ].map(([label, value]) => <div key={String(label)}><dt className="text-muted">{label}</dt><dd className="mt-1.5 break-words">{value ?? '未知'}</dd></div>)}</dl>
      {[["票息说明", data.coupon_text], ["赎回条款原文", data.call_clause_text], ["回售条款原文", data.put_clause_text]].map(([label, text]) => <details key={label} className="rounded-card border border-border p-3" open={label === '票息说明'}><summary className="cursor-pointer text-xs font-semibold">{label}</summary><p className="mt-3 whitespace-pre-wrap break-words text-xs leading-7 text-secondary">{text || '源未提供'}</p></details>)}
      <section className="rounded-card border border-border p-3"><h4 className="mb-3 text-xs font-semibold">源披露重要日期（非公告全文）</h4>{data.events.length ? <ul className="space-y-2 text-xs">{data.events.map((event, i) => <li key={i} className="flex flex-wrap justify-between gap-2"><span>{event.type}</span><span className="text-muted">{event.start_date ?? '未知'}{event.end_date && ` 至 ${event.end_date}`}</span></li>)}</ul> : <p className="text-xs text-muted">暂无可核对的重要日期记录。</p>}</section>
      <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="inline-block text-xs text-accent">查看公开资料原页 →</a>
      <p className="text-[11px] text-muted">获取时间 {new Date(data.fetched_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</p>
      <SourceTrail data={data} />
    </>}
  </section>
}
