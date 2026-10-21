import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownUp, ArrowLeftRight, ChevronLeft, ChevronRight, Database, FileUp, Info, Loader2, RefreshCw, Search } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { api, type ConvertibleDataset } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { filterConvertibles, sortConvertibles, type ConvertibleFilters, type ConvertibleSort, type SortDirection } from './filter'
import { ConvertibleTable } from './ConvertibleTable'
import { ImportPanel } from './ImportPanel'

const PAGE_SIZE = 50
const BUTTON = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border px-3 py-2 text-xs font-medium transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40'
const EMPTY_FILTERS: ConvertibleFilters = { search: '', maxPrice: '', maxPremium: '', maxDoubleLow: '' }

export function ConvertiblesPage() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: QK.convertibles, queryFn: api.convertibles, staleTime: 30_000, retry: false })
  const [showImport, setShowImport] = useState(false)
  const [filters, setFilters] = useState<ConvertibleFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<ConvertibleSort>('double_low')
  const [direction, setDirection] = useState<SortDirection>('asc')
  const [page, setPage] = useState(1)
  const dataset = query.data
  const filtered = useMemo(() => sortConvertibles(filterConvertibles(dataset?.items ?? [], filters), sort, direction), [dataset, filters, sort, direction])
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const activePage = Math.min(page, pageCount)
  const rows = filtered.slice((activePage - 1) * PAGE_SIZE, activePage * PAGE_SIZE)
  const computedCount = dataset?.items.filter(item => item.double_low !== null).length ?? 0
  const setFilter = (key: keyof ConvertibleFilters, value: string) => { setFilters(current => ({ ...current, [key]: value })); setPage(1) }
  const saved = async (next: ConvertibleDataset) => {
    // 取消导入前开始的读取，避免迟到的旧快照覆盖本次保存结果。
    await client.cancelQueries({ queryKey: QK.convertibles, exact: true })
    client.setQueryData(QK.convertibles, next)
    setShowImport(false)
    setPage(1)
    setFilters(EMPTY_FILTERS)
    toast(`已保存 ${next.items.length} 条可转债数据`, 'success')
  }

  return (
    <div className="min-w-0">
      <PageHeader title="可转债研究" subtitle="导入行情快照 · 转股价值 · 溢价率 · 双低排序" right={<span className="shrink-0 rounded-full bg-elevated px-2.5 py-1 text-[10px] text-secondary">快照研究</span>} />
      <div className="mx-auto max-w-[1600px] space-y-5 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="flex items-center gap-2 text-xs text-secondary"><Database className="h-3.5 w-3.5 text-muted" />数据源：用户导入<span className="text-muted">· 未接入实时行情</span></p><div className="flex gap-2"><button type="button" onClick={() => void query.refetch()} disabled={query.isFetching} className={BUTTON}><RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />刷新</button><button type="button" onClick={() => setShowImport(true)} disabled={showImport || !dataset} className={`${BUTTON} border-accent/30 bg-accent/10 text-accent hover:bg-accent/15`}><FileUp className="h-3.5 w-3.5" />导入 CSV</button></div></div>

        {query.isPending && <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />正在读取研究清单…</div>}
        {query.isError && !dataset && <ErrorState title="研究清单读取失败" hint={query.error.message} onRetry={() => void query.refetch()} retrying={query.isFetching} />}
        {query.isError && dataset && <p role="alert" className="rounded-card border border-danger/25 bg-danger/5 p-3 text-xs text-danger">刷新失败：{query.error.message}。下方保留上次成功读取的快照。</p>}
        {showImport && dataset && <ImportPanel existingCount={dataset.items.length} onClose={() => setShowImport(false)} onSaved={saved} />}

        {dataset && <>
          {dataset.items.length > 0 ? <>
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3"><div className="rounded-card border border-border bg-surface p-4"><dt className="text-[11px] text-muted">研究清单</dt><dd className="mt-2 font-mono text-2xl font-semibold tabular-nums">{dataset.items.length}<span className="ml-2 font-sans text-xs font-normal text-muted">只转债</span></dd></div><div className="rounded-card border border-border bg-surface p-4"><dt className="text-[11px] text-muted">数据日期（由导入者提供）</dt><dd className="mt-2 font-mono text-2xl font-semibold tabular-nums">{dataset.as_of || '—'}</dd></div><div className="rounded-card border border-border bg-surface p-4"><dt className="text-[11px] text-muted">可计算双低值</dt><dd className="mt-2 font-mono text-2xl font-semibold tabular-nums">{computedCount}<span className="ml-2 font-sans text-xs font-normal text-muted">/ {dataset.items.length} 只</span></dd></div></dl>

            <section aria-label="可转债筛选" className="overflow-hidden rounded-card border border-border bg-surface">
              <div className="space-y-4 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-sm font-semibold">转债列表 <span className="ml-1 font-mono text-xs font-normal text-muted">{filtered.length} / {dataset.items.length}</span></h2><button type="button" onClick={() => { setFilters(EMPTY_FILTERS); setPage(1) }} className="text-[11px] text-accent hover:underline">清空筛选</button></div>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-[minmax(200px,1.5fr)_repeat(3,minmax(110px,1fr))]">
                  <div className="col-span-2 lg:col-span-1"><label htmlFor="convertible-search" className="mb-1.5 block text-[11px] text-muted">搜索转债 / 正股</label><div className="relative"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted" /><input id="convertible-search" value={filters.search} onChange={event => setFilter('search', event.target.value)} placeholder="名称或代码" className="h-9 w-full rounded-input border border-border bg-base pl-8 pr-3 text-xs outline-none focus:border-accent" /></div></div>
                  {([{ key: 'maxPrice', label: '最高现价（元）', min: 0 }, { key: 'maxPremium', label: '最高溢价率（%）' }, { key: 'maxDoubleLow', label: '最高双低值' }] as const).map(input => <div key={input.key}><label htmlFor={`convertible-${input.key}`} className="mb-1.5 block text-[11px] text-muted">{input.label}</label><input id={`convertible-${input.key}`} type="number" step="any" min={'min' in input ? input.min : undefined} value={filters[input.key]} onChange={event => setFilter(input.key, event.target.value)} placeholder="不限" className="h-9 w-full rounded-input border border-border bg-base px-3 font-mono text-xs outline-none focus:border-accent" /></div>)}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-[11px] text-muted">设置数值上限后，缺少该数值的转债会被排除。</p><div className="flex items-center gap-2"><label htmlFor="convertible-sort" className="text-[11px] text-muted">排序</label><select id="convertible-sort" value={sort} onChange={event => { setSort(event.target.value as ConvertibleSort); setPage(1) }} className="h-8 rounded-input border border-border bg-base px-2 text-xs"><option value="double_low">双低值</option><option value="bond_price">转债现价</option><option value="conversion_premium_pct">转股溢价率</option><option value="maturity_date">到期日</option></select><button type="button" onClick={() => { setDirection(current => current === 'asc' ? 'desc' : 'asc'); setPage(1) }} className={`${BUTTON} py-1.5`} aria-label={`当前${direction === 'asc' ? '升序' : '降序'}，点击切换排序方向`}><ArrowDownUp className="h-3 w-3" />{direction === 'asc' ? '升序' : '降序'}</button></div></div>
              </div>
              {rows.length ? <ConvertibleTable items={rows} caption={`可转债研究清单，数据日期 ${dataset.as_of || '未知'}`} /> : <EmptyState icon={Search} title="没有符合筛选条件的转债" hint="尝试放宽价格、溢价率或双低值上限，也可清空筛选查看完整清单。" />}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-[11px] text-muted"><span>每页 {PAGE_SIZE} 条 · 缺失值始终排在最后</span><div className="flex items-center gap-3"><button type="button" aria-label="上一页" onClick={() => setPage(activePage - 1)} disabled={activePage <= 1} className="rounded p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button><span className="font-mono">{activePage} / {pageCount}</span><button type="button" aria-label="下一页" onClick={() => setPage(activePage + 1)} disabled={activePage >= pageCount} className="rounded p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button></div></div>
            </section>
          </> : !showImport && <section className="rounded-card border border-dashed border-border bg-surface/30 pb-8 text-center"><EmptyState icon={ArrowLeftRight} title="建立你的可转债研究清单" hint="导入转债价格、正股价格与转股价，自动计算转股价值、溢价率和双低值。先预览，再保存。" /><button type="button" onClick={() => setShowImport(true)} className={`${BUTTON} border-accent/30 bg-accent/10 text-accent`}><FileUp className="h-3.5 w-3.5" />导入第一份清单</button></section>}

          <section className="rounded-card border border-border bg-surface/40 p-4 text-[11px] leading-relaxed text-muted"><h2 className="mb-2 flex items-center gap-1.5 font-medium text-secondary"><Info className="h-3.5 w-3.5" />计算口径</h2><div className="grid gap-2 lg:grid-cols-3"><p>转股价值 = 面值 × 正股价 ÷ 转股价。缺少必要价格时返回未知，不按零计算。</p><p>转股溢价率 =（转债现价 ÷ 转股价值 − 1）× 100%。表中 20% 表示百分数 20。</p><p>双低值 = 转债现价 + 溢价率百分数，例如 110 + 20 = 130。它是排序指标，不是预期收益。</p></div><p className="mt-3 border-t border-border pt-3">强赎状态由导入内容提供，未提供时显示“未知”。本页尚未自动接入强赎公告、到期收益率或交易功能。</p></section>
        </>}
      </div>
    </div>
  )
}
