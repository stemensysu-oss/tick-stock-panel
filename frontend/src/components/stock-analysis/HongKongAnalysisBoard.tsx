import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtPct, fmtPrice } from '@/lib/format'
import { AnalysisKChart, type LevelType, type PriceLevel } from './AnalysisKChart'

export function HongKongAnalysisBoard({ symbol }: { symbol: string }) {
  const client = useQueryClient()
  const reload = useMutation({ mutationFn: () => api.stockAnalysisHk(symbol, true), onSuccess: data => client.setQueryData(QK.stockAnalysisHk(symbol), data) })
  const query = useQuery({ queryKey: QK.stockAnalysisHk(symbol), queryFn: () => api.stockAnalysisHk(symbol), staleTime: 300_000, retry: false })
  const data = query.data
  return <section aria-label="港股日K与关键价位" className="rounded-card border border-border bg-surface/40 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">港股日K与关键价位{data ? ' · HKD 港元' : ''}</h2><button type="button" disabled={query.isFetching || reload.isPending} onClick={() => reload.mutate()} className="inline-flex items-center gap-1 rounded-btn border border-border px-3 py-1 text-xs"><RefreshCw className="h-3 w-3" />{query.isFetching || reload.isPending ? '读取中…' : '刷新港股分析数据'}</button></div>
    {query.isPending && <p role="status" className="py-8 text-muted">正在读取港股日K与来源信息…</p>}
    {reload.isError && <p role="alert" className="my-4 text-warning">刷新失败，原有数据保留：{reload.error.message}</p>}
    {query.isError && <p role="alert" className="my-4 text-warning">读取失败，已有数据保留：{query.error.message}</p>}
    {data && <>
      <p className="mt-3 text-sm">{data.name} · {data.symbol} · {data.rows.length}个已完成交易日</p>
      <p className="mt-2 text-xs text-muted">历史末日 {data.as_of} · 历史收盘 {fmtPrice(data.close)} HKD · 不复权</p>
      <p className="mt-2 text-xs text-muted">报价快照 {fmtPrice(data.quote.close)} HKD（{fmtPct(data.quote.change_pct)}）· 来源时点 {data.quote.quote_at} · {data.quote.quote_source}</p>
      <p className="mt-2 text-xs text-muted">日K来源：{data.source_name} · 抓取时间：{data.fetched_at} · 成交量为来源原单位</p>
      {data.warnings.map((warning, i) => <p key={i} className="mt-2 text-xs text-warning">{warning}</p>)}
      <AnalysisKChart rows={data.rows} levels={data.levels as Record<LevelType, PriceLevel[]>} series={data.series} seriesDates={data.dates} defaultLevelTypes={['pivot','extreme','keltner_s']} height={480} />
      <p className="mt-3 text-xs text-muted">点击上方“AI 港股技术分析”使用已配置的AI服务解读这份数据。未配置时可继续查看图表与关键价位。</p>
    </>}
  </section>
}
