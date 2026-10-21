import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChartNoAxesCombined, Database, Info, Loader2, RefreshCw, Search } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { api, type FundNavRange } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { FundNavChart } from './FundNavChart'

const RANGES: { value: FundNavRange; label: string }[] = [
  { value: 'week', label: '近一周' }, { value: 'month', label: '近一月' },
  { value: 'tmonth', label: '近三月' }, { value: 'hyear', label: '近半年' },
  { value: 'year', label: '近一年' }, { value: 'twoyear', label: '近两年' },
  { value: 'tyear', label: '近三年' }, { value: 'fyear', label: '近五年' },
]
const BUTTON = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border px-3 py-2 text-xs font-medium transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40'
const ASSET_LABELS: Record<string, string> = { stock: '股票', bond: '债券', fund: '基金', unknown: '未知' }

function number(value: number | null | undefined, digits = 4) {
  return value == null ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function percent(value: number | null | undefined) {
  return value == null ? '—' : `${number(value, 2)}%`
}

function Loading({ text }: { text: string }) {
  return <div role="status" className="flex min-h-36 items-center justify-center gap-2 p-8 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />{text}</div>
}

export function FundsPage() {
  const [input, setInput] = useState('')
  const [ticker, setTicker] = useState('')
  const [inputError, setInputError] = useState('')
  const [range, setRange] = useState<FundNavRange>('year')
  const [navField, setNavField] = useState<'unit_nav' | 'adj_nav'>('unit_nav')
  const status = useQuery({ queryKey: QK.fundResearchStatus, queryFn: api.fundResearchStatus, staleTime: 30_000, retry: false })
  const enabled = !!ticker && status.data?.configured === true
  const profile = useQuery({ queryKey: QK.fundProfile(ticker), queryFn: () => api.fundProfile(ticker), enabled, staleTime: 300_000, retry: false })
  const nav = useQuery({ queryKey: QK.fundNav(ticker, range), queryFn: () => api.fundNav(ticker, range), enabled, staleTime: 300_000, retry: false })
  const holdings = useQuery({ queryKey: QK.fundHoldings(ticker), queryFn: () => api.fundHoldings(ticker), enabled, staleTime: 300_000, retry: false })
  const refreshing = profile.isFetching || nav.isFetching || holdings.isFetching
  const refresh = () => { void profile.refetch(); void nav.refetch(); void holdings.refetch() }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const next = input.trim().toUpperCase()
    if (!/^\d{6}\.(OF|SH|SZ)$/.test(next)) {
      setInputError('请输入完整基金代码，例如 000001.OF、510300.SH 或 159915.SZ。')
      return
    }
    setInputError('')
    setInput(next)
    if (next === ticker) refresh()
    else setTicker(next)
  }
  const points = nav.data?.items ?? []
  const lastPoint = points.findLast(point => point[navField] !== null)
  const fund = profile.data?.profile

  return (
    <div className="min-w-0">
      <PageHeader title="基金研究" subtitle="基金资料 · 历史净值 · 定期披露持仓" right={<span className="shrink-0 rounded-full bg-accent/10 px-2.5 py-1 text-[10px] font-medium text-accent">基金 / ETF / LOF</span>} />
      <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
        <section className="rounded-card border border-border bg-surface p-4 sm:p-5">
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label htmlFor="fund-ticker" className="mb-2 block text-xs font-medium text-secondary">基金代码</label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" />
                <input id="fund-ticker" value={input} onChange={event => { setInput(event.target.value); setInputError('') }} placeholder="输入完整代码，如 000001.OF" autoComplete="off" spellCheck={false} maxLength={12} aria-invalid={!!inputError} aria-describedby="fund-code-help" className="h-10 w-full rounded-input border border-border bg-base pl-9 pr-3 font-mono text-sm outline-none focus:border-accent" />
              </div>
            </div>
            <button type="submit" disabled={status.data?.configured !== true || refreshing || !input.trim()} className={`${BUTTON} h-10 border-accent/30 bg-accent text-white hover:bg-accent/90`}>
              {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}查询基金
            </button>
          </form>
          <p id="fund-code-help" className="mt-2 text-[11px] leading-relaxed text-muted">场外基金使用 .OF，场内基金使用 .SH / .SZ；代码后缀由你明确选择。</p>
          {inputError && <p role="alert" className="mt-2 text-xs text-danger">{inputError}</p>}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3 text-xs">
            <span className="flex items-center gap-2 text-secondary"><Database className="h-3.5 w-3.5 text-muted" />数据源：扶摇{status.data?.configured && <span className="text-muted">· 已配置，权限以查询结果为准</span>}</span>
            <button type="button" onClick={() => void status.refetch()} disabled={status.isFetching} className="flex items-center gap-1.5 text-accent disabled:opacity-40"><RefreshCw className={cn('h-3 w-3', status.isFetching && 'animate-spin')} />重新检查配置</button>
          </div>
          {status.isPending && <p role="status" className="mt-3 text-xs text-muted">正在检查基金数据源配置…</p>}
          {status.isError && <p role="alert" className="mt-3 text-xs text-danger">配置读取失败：{status.error.message}</p>}
          {status.data && !status.data.configured && <div role="status" className="mt-3 rounded-btn border border-warning/25 bg-warning/5 p-3 text-xs leading-relaxed text-secondary"><p>{status.data.message}</p><Link to="/settings?tab=data-sources" className="mt-2 inline-flex font-medium text-accent hover:underline">前往数据源配置 →</Link><p className="mt-1 text-muted">含 A 股行情权限的 Key 可在现有数据源设置页保存。仅有基金接口权限的 Key，请通过后端环境变量 FUYAO_API_KEY 配置并重启服务，再点击“重新检查配置”。接口权限以实际查询结果为准。</p></div>}
        </section>

        {!ticker && <section className="rounded-card border border-dashed border-border bg-surface/30"><EmptyState icon={ChartNoAxesCombined} title="从一只基金开始研究" hint="输入基金代码，查看管理人、净值走势和已披露持仓。这里展示日级净值与定期报告，不提供盘中估值。" /></section>}

        {enabled && <>
          <section aria-label="基金资料" className="rounded-card border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
              <div className="min-w-0"><h2 className="break-words text-[16px] font-semibold text-foreground">{fund?.fund_name || '基金资料'}</h2><p className="mt-1 font-mono text-xs text-muted">{ticker}</p></div>
              <button type="button" onClick={refresh} disabled={refreshing} className={BUTTON}><RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />刷新</button>
            </div>
            {profile.isPending ? <Loading text="正在读取基金资料…" /> : profile.isError ? <ErrorState title="基金资料读取失败" hint={profile.error.message} onRetry={() => void profile.refetch()} retrying={profile.isFetching} /> : !fund ? <EmptyState title="暂无基金资料" hint="数据源未返回这只基金的资料；其他数据会独立显示。" /> : <dl className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-4 sm:p-5">{[
              ['基金经理', fund.manager_name || '—'], ['基金管理人', fund.mgmt_name || '—'],
              ['成立日期', fund.established_date || '—'], ['资料中的单位净值', number(fund.unit_nav)],
            ].map(([label, value]) => <div key={label}><dt className="text-[11px] text-muted">{label}</dt><dd className="mt-2 break-words text-sm font-medium text-foreground">{value}</dd></div>)}</dl>}
          </section>

          <section aria-label="净值走势" className="rounded-card border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-4 px-4 pt-4 sm:px-5">
              <div><h2 className="text-sm font-semibold">净值走势</h2><p className="mt-1 text-[11px] text-muted">{lastPoint ? `所选区间最近净值日 ${lastPoint.date} · ${number(lastPoint[navField])}` : '以数据源公布的净值日期为准'}</p></div>
              <div className="flex rounded-btn bg-elevated/70 p-1">{(['unit_nav', 'adj_nav'] as const).map(field => <button key={field} type="button" onClick={() => setNavField(field)} aria-pressed={navField === field} className={cn('rounded px-3 py-1.5 text-xs transition-colors', navField === field ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground')}>{field === 'unit_nav' ? '单位净值' : '复权净值'}</button>)}</div>
            </div>
            <div className="flex flex-wrap gap-1 px-4 pt-4 sm:px-5">{RANGES.map(option => <button type="button" key={option.value} aria-pressed={range === option.value} onClick={() => setRange(option.value)} className={cn('rounded-btn px-2.5 py-1.5 text-[11px]', range === option.value ? 'bg-accent/10 font-medium text-accent' : 'text-muted hover:bg-elevated hover:text-secondary')}>{option.label}</button>)}</div>
            {nav.isPending ? <Loading text="正在读取历史净值…" /> : nav.isError ? <ErrorState title="历史净值读取失败" hint={nav.error.message} onRetry={() => void nav.refetch()} retrying={nav.isFetching} /> : !lastPoint ? <EmptyState title="所选区间暂无该口径净值" hint="可尝试其他区间，或切换单位净值 / 复权净值。缺失值不会填成零。" /> : <FundNavChart items={points} field={navField} />}
            <p className="flex gap-2 border-t border-border px-4 py-3 text-[11px] leading-relaxed text-muted sm:px-5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />净值沿用数据源币种，未做汇率换算。单位净值变化会受分红、份额折算等影响，不等同投资总回报。复权净值沿用数据源口径，不是累计净值。</p>
          </section>

          <section aria-label="披露持仓" className="overflow-hidden rounded-card border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5"><div><h2 className="text-sm font-semibold">披露持仓</h2><p className="mt-1 text-[11px] text-muted">持仓来自定期披露，请同时核对报告期与公告日。</p></div>{holdings.data && <div className="flex flex-wrap gap-3 text-[11px] text-secondary"><span>股票 {percent(holdings.data.stock_ratio_pct)}</span><span>债券 {percent(holdings.data.bond_ratio_pct)}</span><span>基金 {percent(holdings.data.fund_ratio_pct)}</span></div>}</div>
            {holdings.isPending ? <Loading text="正在读取披露持仓…" /> : holdings.isError ? <ErrorState title="持仓读取失败" hint={holdings.error.message} onRetry={() => void holdings.refetch()} retrying={holdings.isFetching} /> : !holdings.data?.items.length ? <EmptyState title="暂无已披露持仓" hint="数据源未返回持仓记录。这不代表基金当前没有持仓。" /> : <div className="overflow-x-auto"><table className="w-full min-w-[660px] text-left text-xs"><caption className="sr-only">{ticker} 披露持仓；占净值比重为百分数</caption><thead className="border-y border-border bg-elevated/40 text-[11px] text-muted"><tr>{['资产', '类型', '占净值比重', '报告期', '公告日'].map(label => <th key={label} className="px-4 py-2.5 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{holdings.data.items.map((item, index) => <tr key={`${item.asset_type}-${item.ticker}-${item.report_date}-${index}`} className="hover:bg-elevated/30"><td className="px-4 py-3"><div className="font-medium text-foreground">{item.name || '未提供名称'}</div><div className="mt-1 font-mono text-[10px] text-muted">{item.ticker}</div></td><td className="px-4 py-3 text-secondary">{ASSET_LABELS[item.asset_type] || item.asset_type}</td><td className="px-4 py-3 font-mono tabular-nums">{percent(item.weight_pct)}</td><td className="px-4 py-3 font-mono text-secondary">{item.report_date || '—'}</td><td className="px-4 py-3 font-mono text-secondary">{item.publish_date || '—'}</td></tr>)}</tbody></table></div>}
          </section>
        </>}
      </div>
    </div>
  )
}
