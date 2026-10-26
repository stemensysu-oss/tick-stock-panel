import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownUp, ArrowLeftRight, ChevronLeft, ChevronRight, Database, Download, FileUp, Info, Loader2, RefreshCw, Search, UploadCloud } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { FormulaEditor, emptySettings } from './FormulaEditor'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { api, type ConvertibleDataset, type ConvertibleCalculationSettings } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { EMPTY_FILTERS, filterConvertibles, sortConvertibles, type ConvertibleFilters, type ConvertibleSort, type SortDirection } from './filter'
import { COLUMNS, BUTTON } from './columns'
import { ConvertibleTable } from './ConvertibleTable'
import { ImportPanel } from './ImportPanel'
import { RestorePanel } from './RestorePanel'
import { FilterBar } from './ConvertibleFilters'
import { ConvertibleDetail } from './ConvertibleDetail'
import { ConvertibleClauseTable, ConvertibleComparison, ConvertibleEvents, ConvertibleScatter } from './ConvertibleViews'
import { codeIdentity, useResearchPreferences } from './preferences'
import { withReference } from './reference'
import { SourceTrail } from '../SourceTrail'
import { createConvertibleCsv, downloadText } from './export'

const PAGE_SIZE = 50
type View = 'list' | 'call' | 'put' | 'revision' | 'announcements' | 'scatter' | 'compare'
const VIEWS: { id: View; label: string }[] = [{ id: 'list', label: '转债列表' }, { id: 'call', label: '强赎观察' }, { id: 'put', label: '回售观察' }, { id: 'revision', label: '下修记录' }, { id: 'announcements', label: '公告' }, { id: 'scatter', label: '散点图' }, { id: 'compare', label: '对比' }]

export function ConvertiblesPage() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: QK.convertibles, queryFn: api.convertibles, staleTime: 30_000, retry: false })
  const status = useQuery({ queryKey: QK.convertibleSourceStatus, queryFn: api.convertibleSourceStatus, staleTime: 30_000, retry: false })
  const { preferences, update, toggle, storageWarning } = useResearchPreferences()
  const [formulaDraft, setFormulaDraft] = useState<ConvertibleCalculationSettings | null>(null)
  const [formulaBase, setFormulaBase] = useState('')
  const [formulaDiscard, setFormulaDiscard] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [showRestore, setShowRestore] = useState(false)
  const [filters, setFilters] = useState<ConvertibleFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<ConvertibleSort>('double_low')
  const [direction, setDirection] = useState<SortDirection>('asc')
  const [page, setPage] = useState(1)
  const [view, setView] = useState<View>('list')
  const [scope, setScope] = useState<'all' | 'watched' | 'hidden'>('all')
  const [comparison, setComparison] = useState<string[]>([])
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const rawDataset = query.data
  const calculated = useQuery({ queryKey: QK.convertibleCalculated(rawDataset?.revision), queryFn: () => api.calculateConvertibles(rawDataset!.revision), enabled: Boolean(rawDataset?.items.length), staleTime: 30_000, retry: false })
  // A result belongs only to its raw revision. Never merge a late pre-save response.
  const activeCalculation = calculated.data?.revision === rawDataset?.revision ? calculated.data : undefined
  const referenceMap = useMemo(() => new Map(activeCalculation?.references.map(item => [codeIdentity(item.code), item])), [activeCalculation])
  const dataset = useMemo(() => rawDataset ? { ...rawDataset, items: (activeCalculation?.items ?? rawDataset.items).map(item => {
    const awaitingCustom = !activeCalculation && (Object.keys(rawDataset.calculation_settings?.formulas ?? {}).length > 0 || Object.keys(item.research?.calculation_settings?.formulas ?? {}).length > 0)
    const pending = awaitingCustom ? Object.fromEntries(['stock_pb', 'stock_volatility_pct', 'outstanding_amount', 'fund_holding_pct', 'conversion_value', 'conversion_premium_pct', 'double_low', 'remaining_years', 'debt_to_float_cap_pct', 'call_trigger_price', 'put_trigger_price', 'pure_bond_value', 'option_value', 'ytm_pct', 'put_yield_pct'].map(key => [key, null])) : {}
    return withReference({ ...item, ...pending }, referenceMap.get(codeIdentity(item.code)), rawDataset.as_of)
  }) } : undefined, [rawDataset, activeCalculation, referenceMap])
  const selected = dataset?.items.find(item => item.code === selectedCode)
  const scoped = useMemo(() => (dataset?.items ?? []).filter(item => scope === 'hidden' ? preferences.hidden.includes(codeIdentity(item.code)) : !preferences.hidden.includes(codeIdentity(item.code)) && (scope !== 'watched' || preferences.watched.includes(codeIdentity(item.code)))), [dataset, preferences.hidden, preferences.watched, scope])
  const filtered = useMemo(() => sortConvertibles(filterConvertibles(scoped, filters), sort, direction), [scoped, filters, sort, direction])
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const activePage = Math.min(page, pageCount)
  const rows = filtered.slice((activePage - 1) * PAGE_SIZE, activePage * PAGE_SIZE)
  const computedCount = dataset?.items.filter(item => item.double_low != null).length ?? 0
  const callItems = filtered.filter(item => item.research?.call_clause || item.redemption_status || item.research?.events.some(event => event.type === 'call'))
  const putItems = filtered.filter(item => item.research?.put_clause || item.research?.events.some(event => event.type === 'put'))
  const compareItems = dataset?.items.filter(item => comparison.includes(codeIdentity(item.code))) ?? []
  const setFilter = (key: keyof ConvertibleFilters, value: string) => { setFilters(current => ({ ...current, [key]: value })); setPage(1) }
  const applySnapshot = async (next: ConvertibleDataset) => {
    // Reads that started before this write must not replace its returned snapshot.
    await client.cancelQueries({ queryKey: QK.convertibles, exact: true })
    client.setQueryData(QK.convertibles, next)
    void client.invalidateQueries({ queryKey: QK.convertibleSourceStatus, exact: true })
  }
  const imported = async (next: ConvertibleDataset) => {
    await applySnapshot(next)
    setShowImport(false); setShowRestore(false); setSelectedCode(null); setPage(1); setFilters(EMPTY_FILTERS)
    setComparison(current => current.filter(code => next.items.some(item => codeIdentity(item.code) === code)))
    toast(`已保存 ${next.items.length} 条可转债数据`, 'success')
  }
  const refresh = useMutation({ mutationFn: api.refreshConvertibles, onSuccess: async next => { await applySnapshot(next); toast('行情已更新，正在核对条款与估值日期', 'success') } })
  const formulaPreview = useMutation({ mutationFn: (settings: ConvertibleCalculationSettings) => api.calculateConvertibles(formulaBase, settings) })
  const formulaSave = useMutation({ mutationFn: (settings: ConvertibleCalculationSettings) => api.saveConvertibleCalculationSettings(formulaBase, settings), onSuccess: async next => { await applySnapshot(next); setFormulaDraft(null); toast('公式与参数已保存', 'success') } })
  const closeFormula = () => { if (formulaSave.isPending || formulaPreview.isPending) return; if (JSON.stringify(formulaDraft) !== JSON.stringify(rawDataset?.calculation_settings ?? emptySettings())) setFormulaDiscard(true); else setFormulaDraft(null) }
  const initialized = useRef(false)
  useEffect(() => {
    if (dataset && !dataset.items.length && !initialized.current && !showImport && !showRestore) {
      initialized.current = true
      refresh.mutate({ expected_revision: dataset.revision })
    }
  }, [dataset, refresh.mutate, showImport, showRestore])
  const selectCompare = (code: string) => {
    const identity = codeIdentity(code)
    if (comparison.includes(identity)) setComparison(current => current.filter(value => value !== identity))
    else if (comparison.length < 4) setComparison(current => [...current, identity])
    else toast('最多同时对比 4 只转债，请先移除一只')
  }
  const changeSort = (field: ConvertibleSort) => { if (sort === field) setDirection(current => current === 'asc' ? 'desc' : 'asc'); else { setSort(field); setDirection('asc') } setPage(1) }

  return <div className="min-w-0">
    <PageHeader title="可转债工作台" right={<span className="shrink-0 rounded-full bg-accent/10 px-2.5 py-1 text-[10px] text-accent">研究扩展</span>} />
    <div className="mx-auto max-w-[1900px] space-y-2 p-2 sm:p-3">
      {calculated.isFetching && <p role="status" className="text-[11px] text-muted">正在补齐参考并执行已保存公式…</p>}
      <section aria-label="可转债数据连接" className="space-y-1 rounded border border-border bg-surface px-2 py-1.5">
        <div className="flex flex-wrap items-center justify-between gap-1"><p className="flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-secondary"><Database className="h-3.5 w-3.5 text-accent" /><span>数据源：{dataset?.source || '用户导入'}</span><span className="text-muted">{status.isPending ? '检查配置中' : status.isError ? '连接状态未知' : status.data?.configured ? status.data.last_refresh_at ? '行情曾更新成功 · 请核对报价时间' : '可获取行情 · 等待刷新验证' : '行情 Key 未配置'}</span></p><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void query.refetch()} disabled={query.isFetching || refresh.isPending} className={BUTTON}><RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />重新载入</button><button type="button" onClick={() => { if (dataset) refresh.mutate({ expected_revision: dataset.revision }) }} disabled={!dataset || refresh.isPending || showImport || showRestore} title="空清单获取市场转债；已有清单更新报价，保留条款和研究资料" className={`${BUTTON} border-accent/30 bg-accent/10 text-accent`}>{refresh.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{dataset?.items.length ? '更新行情' : '获取市场清单'}</button><button type="button" onClick={() => { setShowImport(true); setShowRestore(false) }} disabled={showImport || !dataset || refresh.isPending} className={BUTTON}><FileUp className="h-3.5 w-3.5" />导入 CSV</button><button type="button" onClick={() => { setShowRestore(true); setShowImport(false) }} disabled={showRestore || !dataset || refresh.isPending} className={BUTTON}><UploadCloud className="h-3.5 w-3.5" />恢复备份</button></div></div>
        {dataset && dataset.items.length > 0 && <div aria-label="条款与估值补齐" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted"><span>计算日 {dataset.as_of || '—'} · 清单 {dataset.items.length}</span><span>到期日 {dataset.items.filter(i => i.maturity_date != null).length}</span><span>纯债 {dataset.items.filter(i => i.pure_bond_value != null).length}</span><span>双低 {computedCount}</span><span>到期收益 {dataset.items.filter(i => i.ytm_pct != null).length}</span><span>剩余规模 {dataset.items.filter(i => i.outstanding_amount != null).length}</span><button type="button" onClick={() => void calculated.refetch()} disabled={calculated.isFetching} className="text-accent disabled:opacity-40">{calculated.isFetching ? '正在补齐…' : '补齐条款与估值'}</button><button type="button" className="ml-auto text-accent" onClick={() => { setFormulaBase(dataset.revision); setFormulaDraft(structuredClone(rawDataset?.calculation_settings ?? emptySettings())); setFormulaDiscard(false); formulaPreview.reset(); formulaSave.reset() }}>公式与参数</button></div>}
        {calculated.isError && <p role="alert" className="text-xs text-warning">条款与估值读取失败：{calculated.error.message}。保留已有显示，可点击上方重试。</p>}
        {activeCalculation?.reference_status === 'unavailable' && <p role="alert" className="text-xs text-warning">公开参考暂不可用；仅采用已保存人工资料计算，可点击补齐重试。</p>}
        <details className="text-[11px] text-muted"><summary className="cursor-pointer">来源、日期与缺项说明</summary><p>{status.isError ? status.error.message : status.data?.message}</p><SourceTrail data={activeCalculation} /><p>纯债的公开参考与个人公式分开标注。合同现金流为计划情景；基金持仓与波动率未知时不按零填充。全部指标可在显示列勾选，点击转债名称编辑参数和公式。</p></details>
      </section>
      {storageWarning && <p role="status" className="text-xs text-warning">{storageWarning}</p>}
      {refresh.isError && <p role="alert" className="rounded-card border border-danger/25 bg-danger/5 p-3 text-xs text-danger">更新行情失败：{refresh.error.message}。已保存的清单保留，可继续研究或导入 CSV。</p>}
      {query.isPending && <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />正在读取研究清单…</div>}
      {query.isError && !dataset && <ErrorState title="研究清单读取失败" hint={query.error.message} onRetry={() => void query.refetch()} retrying={query.isFetching} />}
      {query.isError && dataset && <p role="alert" className="rounded-card border border-danger/25 bg-danger/5 p-3 text-xs text-danger">刷新失败：{query.error.message}。下方保留上次成功读取的快照。</p>}
      {showImport && dataset && <ImportPanel existingCount={dataset.items.length} onClose={() => setShowImport(false)} onSaved={imported} />}
      {showRestore && dataset && <RestorePanel existingCount={dataset.items.length} onClose={() => setShowRestore(false)} onSaved={imported} />}
      {dataset && <>
        {dataset.items.length > 0 ? <>
          <FilterBar items={dataset.items} filters={filters} setFilter={setFilter} onReset={() => { setFilters(EMPTY_FILTERS); setPage(1) }} columns={preferences.columns} setColumns={columns => update({ ...preferences, columns })} />
          <section className="min-w-0 overflow-hidden rounded-card border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4"><nav aria-label="可转债工作台视图" className="flex max-w-full overflow-x-auto">{VIEWS.map(option => <button type="button" key={option.id} onClick={() => setView(option.id)} aria-current={view === option.id ? 'page' : undefined} className={cn('shrink-0 whitespace-nowrap border-b-2 px-2 py-2 text-xs font-medium', view === option.id ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-foreground')}>{option.label}{option.id === 'compare' && comparison.length > 0 && <span className="ml-1 rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px]">{compareItems.length}</span>}</button>)}</nav><div className="flex flex-wrap items-center gap-2 py-1"><button type="button" onClick={() => downloadText(createConvertibleCsv(filtered, preferences.columns), `convertibles-${dataset.as_of || 'snapshot'}.csv`)} disabled={!filtered.length} className={`${BUTTON} px-2 py-1.5`}><Download className="h-3 w-3" />导出筛选 CSV</button><button type="button" onClick={() => downloadText(JSON.stringify(rawDataset, null, 2), `convertibles-research-${dataset.as_of || 'snapshot'}.json`, 'application/json;charset=utf-8')} className={`${BUTTON} px-2 py-1.5`}><Download className="h-3 w-3" />备份研究</button></div></div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-2 py-1"><div className="flex flex-wrap items-center gap-2"><select aria-label="研究清单范围" value={scope} onChange={event => { setScope(event.target.value as typeof scope); setPage(1) }} className="h-7 rounded-input border border-border bg-base px-2 text-xs"><option value="all">全部（隐藏已排除）</option><option value="watched">我的自选</option><option value="hidden">排除名单</option></select><span className="text-[11px] text-muted">筛选后 <b className="font-mono font-normal text-secondary">{filtered.length}</b> / {dataset.items.length} 只</span>{comparison.length > 0 && <button type="button" onClick={() => setView('compare')} className="text-[11px] text-accent">对比已选 {compareItems.length} 只</button>}</div><div className="flex items-center gap-2"><label htmlFor="convertible-sort" className="text-[11px] text-muted">排序</label><select id="convertible-sort" value={sort} onChange={event => { setSort(event.target.value as ConvertibleSort); setPage(1) }} className="h-7 max-w-36 rounded-input border border-border bg-base px-2 text-xs">{COLUMNS.map(column => <option value={column.id} key={column.id}>{column.label}</option>)}</select><button type="button" onClick={() => { setDirection(current => current === 'asc' ? 'desc' : 'asc'); setPage(1) }} className={`${BUTTON} px-2 py-1.5`} aria-label={`当前${direction === 'asc' ? '升序' : '降序'}，点击切换排序方向`}><ArrowDownUp className="h-3 w-3" />{direction === 'asc' ? '升序' : '降序'}</button></div></div>
            {view === 'list' && (rows.length ? <ConvertibleTable items={rows} caption={`可转债研究清单，计算数据日 ${dataset.as_of || '未知'}`} columns={preferences.columns} sort={sort} direction={direction} onSort={changeSort} watched={preferences.watched} selected={comparison} onWatch={code => toggle('watched', code)} onCompare={selectCompare} onOpen={item => setSelectedCode(item.code)} /> : <EmptyState icon={Search} title="没有符合条件的转债" hint="可放宽筛选、切换清单范围，或清空筛选查看更多标的。" />)}
            {view === 'call' && <ConvertibleClauseTable items={callItems} kind="call" onOpen={item => setSelectedCode(item.code)} />}
            {view === 'put' && <ConvertibleClauseTable items={putItems} kind="put" onOpen={item => setSelectedCode(item.code)} />}
            {(view === 'revision' || view === 'announcements') && <ConvertibleEvents items={filtered} kind={view === 'revision' ? 'revision' : undefined} onOpen={item => setSelectedCode(item.code)} />}
            {view === 'scatter' && <ConvertibleScatter items={filtered} onOpen={item => setSelectedCode(item.code)} />}
            {view === 'compare' && <ConvertibleComparison items={compareItems} onOpen={item => setSelectedCode(item.code)} onRemove={selectCompare} />}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-2 py-1 text-[10px] text-muted"><span>{view === 'compare' ? '对比独立于筛选；各指标须同时核对其数据日期。' : '未知值始终排在最后 · 自选/排除/列设置仅存本机浏览器'}</span>{view === 'list' && <div className="flex items-center gap-3"><span>每页 {PAGE_SIZE} 条</span><button type="button" aria-label="上一页" onClick={() => setPage(activePage - 1)} disabled={activePage <= 1} className="rounded p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button><span className="font-mono">{activePage} / {pageCount}</span><button type="button" aria-label="下一页" onClick={() => setPage(activePage + 1)} disabled={activePage >= pageCount} className="rounded p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button></div>}</div>
          </section>
        </> : !showImport && !showRestore && <section className="rounded-card border border-dashed border-border bg-surface/30 pb-8 text-center"><EmptyState icon={ArrowLeftRight} title="建立你的可转债研究清单" hint="正在尝试获取市场清单；失败时可点击上方获取市场清单重试。也可导入自有资料，条款、公告与现金流仍须独立核验。" /><div className="flex flex-wrap justify-center gap-2"><button type="button" onClick={() => setShowImport(true)} className={`${BUTTON} border-accent/30 bg-accent/10 text-accent`}><FileUp className="h-3.5 w-3.5" />导入第一份清单</button><button type="button" onClick={() => setShowRestore(true)} className={BUTTON}>恢复已有研究备份</button></div></section>}
        <details className="rounded-card border border-border bg-surface/40 p-4 text-[11px] leading-relaxed text-muted"><summary className="cursor-pointer font-medium text-secondary"><Info className="mr-1.5 inline h-3.5 w-3.5" />计算口径与数据边界</summary><div className="mt-3 grid gap-3 lg:grid-cols-3"><p>转股价值 = 100 × 正股不复权价 ÷ 转股价。溢价率 =（现价 ÷ 转股价值 − 1）× 100%。双低值 = 现价 + 溢价率百分数，例如 110 + 20 = 130。</p><p>收益率按人工确认或严格解析的合同计划现金流、含息成本求 IRR；默认 ACT/365，参数与表达式可调整。纯债列优先展示手工模型，否则为带日期的公开模型参考；B-S 期权价值依赖输入参数；回售收益是情景值。</p><p>条件命中与执行强赎分别记录。条款、历史观察、公告和基金持仓必须有明确日期与来源。行情接口未提供的字段保持未知。</p></div><p className="mt-3 border-t border-border pt-3">CSV 导出采用字段原始单位：金额为元、百分比为百分数，包含计算列但不包含详情研究记录；完整人工现金流、条款和公告请使用“备份研究”；联网参考值独立缓存，不写入研究备份。在表格软件中打开 CSV 时请将代码列设置为文本。模型与筛选用于研究，不代表预期收益或交易指令。</p></details>
      </>}
    </div>
    {formulaDraft && dataset && <Modal onClose={closeFormula} labelledBy="global-formula-title" closeOnBackdrop={false} panelClassName="flex max-h-[92vh] w-full max-w-4xl flex-col rounded-card border border-border bg-surface shadow-2xl">
      <header className="flex items-center justify-between border-b border-border p-3"><h2 id="global-formula-title" className="text-sm font-semibold">全局公式与参数模板</h2><button type="button" onClick={closeFormula} className={BUTTON}>关闭</button></header>
      <div className="space-y-3 overflow-y-auto p-3">{formulaDiscard && <div role="alert" className="text-warning">有未保存的参数。<button type="button" className="ml-2 text-accent" onClick={() => setFormulaDiscard(false)}>继续编辑</button><button type="button" className="ml-3 text-danger" onClick={() => setFormulaDraft(null)}>放弃并关闭</button></div>}
        <FormulaEditor value={formulaDraft} onChange={next => { setFormulaDraft(next); formulaPreview.reset(); formulaSave.reset() }} item={formulaPreview.data?.items[0] ?? dataset.items[0]} reference={(formulaPreview.data?.references ?? activeCalculation?.references)?.find(ref => ref.code === (formulaPreview.data?.items[0] ?? dataset.items[0])?.code)} />
        <p className="text-[11px] text-muted">全局预览以首只转债 {dataset.items[0]?.name || '（清单为空）'} 为示例；单只覆盖仍优先。保存后全表重算；完整备份包含参数和公式。</p>
        {(formulaPreview.isError || formulaSave.isError) && <p role="alert" className="text-xs text-danger">{formulaPreview.error?.message || formulaSave.error?.message}。若清单已改变，请关闭后重新打开。</p>}
      </div><footer className="flex justify-end gap-2 border-t border-border p-3"><button type="button" className={BUTTON} disabled={formulaPreview.isPending || formulaSave.isPending || formulaBase !== dataset.revision} onClick={() => formulaPreview.mutate(formulaDraft)}>{formulaPreview.isPending ? '计算中…' : '预览全表'}</button><button type="button" className={`${BUTTON} text-accent`} disabled={formulaPreview.isPending || formulaSave.isPending || formulaBase !== dataset.revision} onClick={() => formulaSave.mutate(formulaDraft)}>{formulaSave.isPending ? '保存中…' : '保存模板'}</button></footer>
    </Modal>}
    {selected && dataset && <ConvertibleDetail key={selected.code} item={selected} globalSettings={rawDataset?.calculation_settings} referenceData={referenceMap.get(codeIdentity(selected.code))} revision={dataset.revision} asOf={dataset.as_of} source={dataset.source} onClose={() => setSelectedCode(null)} onSaved={async next => { await applySnapshot(next); setSelectedCode(null); toast('研究资料和计算结果已保存', 'success') }} watched={preferences.watched.includes(codeIdentity(selected.code))} hidden={preferences.hidden.includes(codeIdentity(selected.code))} onWatch={() => toggle('watched', selected.code)} onHide={() => toggle('hidden', selected.code)} />}
  </div>
}
