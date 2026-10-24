import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

export function HkFinancialStatements({ symbol }: { symbol: string }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: QK.hkFundamentals(symbol), queryFn: () => api.hkFundamentals(symbol), staleTime: 1_800_000, retry: false })
  const reload = useMutation({ mutationFn: () => api.hkFundamentals(symbol, true), onSuccess: data => client.setQueryData(QK.hkFundamentals(symbol), data) })
  const data = query.data
  return <section aria-label="港股财务资料" className="mt-4 rounded-card border border-border p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">财务报表与资料覆盖</h3><button type="button" className="rounded-btn border border-border px-3 py-1 text-xs" disabled={query.isFetching || reload.isPending} onClick={() => reload.mutate()}>刷新财报</button></div>
    {query.isPending && <p role="status" className="mt-3 text-xs text-muted">独立读取财报，不影响日K图表…</p>}
    {(query.isError || reload.isError) && <p role="alert" className="mt-3 text-xs text-warning">财报读取失败，已有资料保留；技术图表仍可使用。</p>}
    {data && <>
      <p className="mt-2 text-xs text-muted">抓取时间 {data.fetched_at} · {data.status === 'stale' ? '保留上次成功资料' : data.status === 'available' ? '三张报表已取得' : data.status === 'partial' ? '部分资料可用' : '尚未取得财报'}</p>
      {Object.entries(data.tables).map(([key, table]) => <div key={key} className="mt-3 rounded-lg border border-border p-3">
        <h4 className="font-medium">{table.label} · {table.reports.length ? `${table.reports.length}个报告期` : '未取得有效数据'}</h4>
        {table.source_url && <a className="text-xs text-accent" href={table.source_url} target="_blank" rel="noreferrer">{table.source === 'eastmoney_public' ? '东方财富公开补充源' : table.source} · 核对来源</a>}
        {table.reports.map(report => <details key={report.period_end} className="mt-2 text-xs">
          <summary className="cursor-pointer">{report.period_end} · {report.report_type} · {report.currency} · {report.items.length}项</summary>
          <p className="my-2 text-muted">期间 {report.period_start || '未知'} 至 {report.period_end}；披露日期 {report.announce_date || '未知，不能用报告期替代'}。{key === 'balance_sheet' ? '期末余额。' : '所列期间累计数。'}</p>
          <div className="max-h-80 overflow-auto"><table className="w-full"><thead><tr className="text-left"><th>科目</th><th className="text-right">数值</th><th className="pl-3">单位</th></tr></thead><tbody>{report.items.map(item => <tr key={item.code} className="border-t border-border/40"><td className="py-1">{item.name}</td><td className="text-right font-mono">{item.value.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}</td><td className="pl-3">{report.currency}{item.unit === 'currency_per_share' ? '/股' : ' 元'}</td></tr>)}</tbody></table></div>
        </details>)}
      </div>)}
      {data.warnings.map((text, i) => <p key={i} className="mt-2 text-xs text-warning">{text}</p>)}
      {data.references.map(link => <a key={link.url} className="mr-4 mt-2 inline-block text-xs text-accent" href={link.url} target="_blank" rel="noreferrer">{link.label}</a>)}
      <p className="mt-2 text-xs text-muted">AI会使用实际取得的报表；市盈率、市净率、每股分红与新闻仍需各自的数据来源，不能从技术指标推断。</p>
    </>}
  </section>
}
