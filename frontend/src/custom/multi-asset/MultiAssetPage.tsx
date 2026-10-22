import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Database, Download, FileUp, FlaskConical, Layers3, Loader2, RefreshCw, Search, SlidersHorizontal, Star } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { api, type MultiAssetCatalog, type MultiAssetCategory, type MultiAssetMode, type MultiAssetSnapshot } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { AssetDetail, AssetTable, researchColumns } from './AssetTable'
import { ImportPanel } from './ImportPanel'
import { SourceTrail } from '../SourceTrail'
import { BUTTON, INPUT, PRIMARY_BUTTON, filterRows, saveCsv, useWorkspacePreferences } from './model'

function Loading({ children }: { children: string }) {
  return <div role="status" className="flex min-h-44 items-center justify-center gap-2 p-6 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />{children}</div>
}

function CapabilityTable({ catalog }: { catalog: MultiAssetCatalog }) {
  return <details className="rounded-card border border-border bg-surface">
    <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-secondary">功能与数据能力一览 · {catalog.categories.length} 类资产</summary>
    <p className="px-4 pb-3 text-xs leading-relaxed text-muted">行情优先 TickFlow、扶摇，失败后才使用公开补充源。事件、净值与交易资格需要独立数据集；不抓取登录后的集思录数据。</p>
    <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><caption className="sr-only">多资产功能与数据源矩阵</caption><thead className="border-y border-border bg-elevated/40 text-muted"><tr>{['类别', '研究能力', '当前数据', '研究字段的候选来源'].map(label => <th key={label} className="px-4 py-2.5 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{catalog.categories.map(category => <tr key={category.id}><td className="whitespace-nowrap px-4 py-3 font-medium">{category.label}</td><td className="px-4 py-3 text-secondary">{category.description}</td><td className="px-4 py-3 text-muted">{category.live_status === 'available' ? '市场行情 / 用户导入 / 演示' : '用户导入 / 演示'}</td><td className="px-4 py-3 text-muted">{category.planned_sources.join('；')}</td></tr>)}</tbody></table></div>
  </details>
}

export function MultiAssetPage({ previewOnly = false }: { previewOnly?: boolean }) {
  const [selected, setSelected] = useState(previewOnly ? '' : 'etf')
  const [mode, setMode] = useState<MultiAssetMode>(previewOnly ? 'demo' : 'market')
  const catalog = useQuery({ queryKey: QK.multiAssetCatalog, queryFn: api.multiAssetCatalog, staleTime: 300_000, retry: false })
  const category = catalog.data?.categories.find(item => item.id === selected) ?? catalog.data?.categories[0]
  return <div className="min-w-0">
    <PageHeader title="多资产工作台" subtitle="按资产组织研究 · 追溯数据来源 · 保留原有工作台" right={<span className="hidden shrink-0 rounded-full bg-accent/10 px-2.5 py-1 text-[10px] font-medium text-accent sm:block">多资产研究 · 第一期</span>} />
    <main className="mx-auto max-w-[1600px] space-y-5 p-4 sm:p-6">
      {previewOnly && <div role="status" className="rounded-card border border-warning/30 bg-warning/5 p-3 text-xs leading-relaxed text-secondary"><strong className="text-warning">单文件演示 · 虚构数据 · 不连接行情</strong><p className="mt-1">可体验分类、筛选、自选与详情；CSV 导入导出和原有模块请在完整 TSP 中使用。</p></div>}
      <section className="flex flex-col gap-4 rounded-card border border-border bg-surface p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="flex items-start gap-3"><span className="rounded-xl bg-accent/10 p-2.5 text-accent"><Layers3 className="h-5 w-5" /></span><div><h2 className="text-sm font-semibold">把研究清单放在同一张工作台</h2><p className="mt-1 text-xs leading-relaxed text-muted">分类浏览、对照指标与来源，逐步接入经验证的数据能力。</p></div></div>
        <div aria-label="数据模式" className="flex shrink-0 rounded-btn bg-elevated/70 p-1">{([{ id: 'market', label: '市场行情', icon: RefreshCw }, { id: 'imported', label: '我的导入数据', icon: Database }, { id: 'demo', label: '虚构演示', icon: FlaskConical }] as const).filter(option => !previewOnly || option.id !== 'market').map(option => <button key={option.id} type="button" onClick={() => setMode(option.id)} aria-pressed={mode === option.id} className={cn('inline-flex items-center justify-center gap-1.5 rounded px-3 py-2 text-xs transition-colors', mode === option.id ? 'bg-surface font-medium text-accent shadow-sm' : 'text-muted hover:text-foreground')}><option.icon className="h-3.5 w-3.5" />{option.label}</button>)}</div>
      </section>
      {catalog.isPending ? <Loading>正在读取资产分类…</Loading> : catalog.isError && !catalog.data ? <ErrorState title="资产分类读取失败" hint={catalog.error.message} onRetry={() => void catalog.refetch()} retrying={catalog.isFetching} /> : !category || !catalog.data ? <EmptyState title="尚未注册资产类别" hint="请检查多资产扩展服务是否启用。" /> : <>
        {catalog.isError && <p role="alert" className="text-xs text-danger">分类刷新失败，保留上次结果：{catalog.error.message}</p>}
        <nav aria-label="资产类别" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{catalog.data.categories.map(item => <button key={item.id} type="button" aria-label={item.label} aria-pressed={category.id === item.id} onClick={() => setSelected(item.id)} className={cn('min-w-0 rounded-card border px-3 py-3 text-left transition-colors', category.id === item.id ? 'border-accent/40 bg-accent/10' : 'border-border bg-surface hover:border-accent/25 hover:bg-elevated/50')}><span className={cn('block text-sm font-medium', category.id === item.id ? 'text-accent' : 'text-secondary')}>{item.label}</span><span className="mt-1 block truncate text-[10px] text-muted" title={item.description}>{item.description}</span></button>)}</nav>
        <CategoryWorkspace key={`${category.id}:${mode}`} category={category} mode={mode} previewOnly={previewOnly} onDemo={() => setMode('demo')} />
        <CapabilityTable catalog={catalog.data} />
        <section className="flex flex-wrap items-center gap-3 rounded-card border border-border bg-surface p-4 text-xs"><span className="text-muted">继续使用原有模块</span>{catalog.data.existing_modules.map(module => previewOnly ? <span key={module.path} className="rounded-btn bg-elevated/50 px-3 py-2 text-muted">{module.label} · 完整版提供</span> : <Link key={module.path} to={module.path} className={`${BUTTON} text-accent`}>{module.label}<ArrowUpRight className="h-3.5 w-3.5" /></Link>)}</section>
      </>}
    </main>
  </div>
}

function CategoryWorkspace({ category, mode, previewOnly, onDemo }: { category: MultiAssetCategory; mode: MultiAssetMode; previewOnly: boolean; onDemo: () => void }) {
  const client = useQueryClient()
  const snapshot = useQuery({ queryKey: QK.multiAssetSnapshot(category.id, mode), queryFn: () => api.multiAssetSnapshot(category.id, mode), staleTime: 30_000, retry: false })
  const availableColumns = researchColumns(category)
  const { preferences, update, storageWarning } = useWorkspacePreferences(category.id, mode, category.columns)
  const [showImport, setShowImport] = useState(false)
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  async function refreshMarket() {
    if (mode !== 'market') { void snapshot.refetch(); return }
    setRefreshing(true); setDownloadError('')
    try { client.setQueryData(QK.multiAssetSnapshot(category.id, mode), await api.multiAssetSnapshot(category.id, mode, true)) }
    catch (error) { setDownloadError(`刷新失败，保留上次结果：${error instanceof Error ? error.message : '取数失败'}`) }
    finally { setRefreshing(false) }
  }
  const [saved, setSaved] = useState('')
  const [pageIndex, setPageIndex] = useState(0)
  const rows = useMemo(() => filterRows(snapshot.data?.rows ?? [], preferences), [snapshot.data, preferences])
  const selectedRow = snapshot.data?.rows.find(row => row.code === selectedCode)
  const columns = availableColumns.filter(column => preferences.columns.includes(column.key))
  const lastPage = Math.max(0, Math.ceil(rows.length / 50) - 1)
  const page = Math.min(pageIndex, lastPage)
  const visibleRows = rows.slice(page * 50, (page + 1) * 50)
  const canImport = !previewOnly && mode === 'imported' && !!snapshot.data && !snapshot.isError
  async function download(kind: 'template' | 'export') {
    setDownloadError(''); setDownloading(true)
    try { saveCsv(await (kind === 'template' ? api.multiAssetTemplate(category.id) : api.exportMultiAsset(category.id)), `multi-asset-${category.id}${kind === 'template' ? '-template' : ''}.csv`) }
    catch (error) { setDownloadError(error instanceof Error ? error.message : '下载失败，请重试。') }
    finally { setDownloading(false) }
  }
  async function onSaved(data: MultiAssetSnapshot) {
    // A read started before the import must not replace the committed snapshot when it resolves late.
    await client.cancelQueries({ queryKey: QK.multiAssetSnapshots })
    client.setQueryData(QK.multiAssetSnapshot(category.id, 'imported'), data)
    setShowImport(false); setSelectedCode(null); setSaved(`已保存 ${data.rows.length} 条 ${category.label} 导入资料。`)
    await client.invalidateQueries({ queryKey: QK.multiAssetSnapshots })
  }
  function onReload() {
    return client.fetchQuery({ queryKey: QK.multiAssetSnapshot(category.id, 'imported'), queryFn: () => api.multiAssetSnapshot(category.id, 'imported'), staleTime: 0 })
  }
  return <div className="space-y-4">
    <div className={cn('rounded-card border px-4 py-3 text-xs leading-relaxed', mode === 'demo' ? 'border-warning/30 bg-warning/5 text-secondary' : 'border-border bg-surface text-secondary')} role="status">
      <strong className={mode === 'demo' ? 'text-warning' : 'text-foreground'}>{mode === 'demo' ? '当前为虚构演示数据，不可用于投资判断。' : mode === 'market' ? '当前为网络市场行情，来源与报价时间随每行展示。' : '当前为用户导入资料，来源与日期由用户填写，尚未核验。'}</strong><p className="mt-1 text-muted">缺失值显示 --；计算仅使用符合日期、币种及口径要求的已填字段。</p>
    </div>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">{[
      ['当前研究', category.label, category.description],
      [mode === 'demo' ? '虚构样本' : mode === 'market' ? '市场标的' : '本类别导入', snapshot.data ? `${snapshot.data.rows.length} 条` : '--', mode === 'demo' ? '与用户资料分开保存偏好' : mode === 'market' ? '独立于用户导入资料' : '可导入并替换本类别清单'],
      ['数据能力', category.live_status === 'available' ? '可获取行情' : '待接入专用数据', '实际来源及失败回退以查询结果为准'],
    ].map(([label, value, help], index) => <div key={label} className={cn('rounded-card border border-border bg-surface p-4', index === 2 && 'col-span-2 sm:col-span-1')}><p className="text-[11px] text-muted">{label}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-[10px] text-muted">{help}</p></div>)}</div>
    <section className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4"><div><h2 className="text-sm font-semibold">{category.label} · 研究清单</h2><p className="mt-1 text-[10px] text-muted">价格保留原币种；每行显示资料基准日和来源。{snapshot.data?.updated_at ? ` 最近保存：${snapshot.data.updated_at}` : ''}</p></div><div className="flex flex-wrap gap-2">
        <button type="button" className={BUTTON} disabled={snapshot.isFetching || refreshing} onClick={() => void refreshMarket()}><RefreshCw className={cn('h-3.5 w-3.5', snapshot.isFetching && 'animate-spin')} />{mode === 'market' ? (refreshing ? '正在刷新…' : '刷新行情') : '重新读取'}</button>
        {!previewOnly && mode === 'imported' && <><button type="button" className={BUTTON} disabled={downloading || !snapshot.data?.rows.length || snapshot.isError} onClick={() => void download('export')}><Download className="h-3.5 w-3.5" />导出本类别</button><button type="button" className={PRIMARY_BUTTON} disabled={!canImport} onClick={() => { setSaved(''); setShowImport(value => !value) }}><FileUp className="h-3.5 w-3.5" />导入 CSV</button></>}
      </div></div>
      {mode === 'market' && <SourceTrail data={{ attempts: snapshot.data?.attempts }} />}
      {(saved || storageWarning || downloadError) && <div className="space-y-1 border-b border-border px-4 py-3 text-xs">{saved && <p role="status" className="text-accent">{saved}</p>}{storageWarning && <p role="status" className="text-warning">{storageWarning}</p>}{downloadError && <p role="alert" className="text-danger">{downloadError}</p>}</div>}
      {snapshot.isPending ? <Loading>正在读取研究清单…</Loading> : snapshot.isError && !snapshot.data ? <ErrorState title="研究清单读取失败" hint={snapshot.error.message} onRetry={() => void snapshot.refetch()} retrying={snapshot.isFetching} /> : <>
        {snapshot.isError && <p role="alert" className="px-4 py-3 text-xs text-danger">刷新失败，保留上次结果：{snapshot.error.message}</p>}
        {!!snapshot.data?.warnings.length && <ul className="list-inside list-disc space-y-1 px-4 py-3 text-xs text-warning">{snapshot.data.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
        {!snapshot.data?.rows.length ? <div className="px-5 py-10 sm:px-8"><div className="mx-auto max-w-xl text-center"><Database className="mx-auto h-9 w-9 text-muted" strokeWidth={1.5} /><h3 className="mt-4 text-[16px] font-semibold">开始建立 {category.label} 研究清单</h3><p className="mt-2 text-sm leading-relaxed text-secondary">本类别尚未返回可用记录。请查看上方取数说明；可重试获取行情，或切换我的导入数据维护研究资料。</p><div className="mt-5 flex flex-wrap justify-center gap-2"><button type="button" className={PRIMARY_BUTTON} onClick={onDemo}><FlaskConical className="h-3.5 w-3.5" />浏览虚构演示</button>{!previewOnly && <button type="button" className={BUTTON} disabled={downloading} onClick={() => void download('template')}>下载空白模板</button>}</div><ol className="mt-6 grid gap-3 text-left text-xs text-muted sm:grid-cols-3"><li><span className="font-medium text-secondary">01 · 准备资料</span><p className="mt-1">填写代码、币种、实际日期与出处。</p></li><li><span className="font-medium text-secondary">02 · 校验预览</span><p className="mt-1">检查单位、缺失项与计算结果。</p></li><li><span className="font-medium text-secondary">03 · 确认保存</span><p className="mt-1">替换当前类别，建立自己的观察清单。</p></li></ol></div></div> : <>
          <div className="flex flex-wrap items-center gap-3 p-4"><label className="relative min-w-40 flex-1"><span className="sr-only">搜索代码、名称或来源</span><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" /><input className={`${INPUT} w-full pl-9 text-xs`} value={preferences.search} maxLength={200} onChange={event => { update({ ...preferences, search: event.target.value }); setPageIndex(0) }} placeholder="搜索代码、名称或来源" /></label><button type="button" aria-pressed={preferences.watchOnly} onClick={() => { update({ ...preferences, watchOnly: !preferences.watchOnly }); setPageIndex(0) }} className={cn(BUTTON, preferences.watchOnly && 'border-warning/40 text-warning')}><Star className="h-3.5 w-3.5" />只看自选</button><select aria-label="排序字段" value={preferences.sortKey} onChange={event => { update({ ...preferences, sortKey: event.target.value }); setPageIndex(0) }} className={`${INPUT} max-w-48 text-xs`}><option value="">默认顺序</option>{category.columns.map(column => <option key={column.key} value={column.key}>{column.label}</option>)}</select><button type="button" disabled={!preferences.sortKey} className={BUTTON} onClick={() => update({ ...preferences, descending: !preferences.descending })}>{preferences.descending ? '降序 ↓' : '升序 ↑'}</button></div>
          <details className="border-t border-border px-4 py-2 text-xs"><summary className="flex cursor-pointer items-center gap-1.5 text-muted"><SlidersHorizontal className="h-3.5 w-3.5" />展示字段 · {columns.length} 项</summary><div className="flex flex-wrap gap-x-5 gap-y-3 py-3">{availableColumns.map(column => <label key={column.key} className="flex cursor-pointer items-center gap-2 text-secondary"><input type="checkbox" checked={preferences.columns.includes(column.key)} onChange={event => update({ ...preferences, columns: event.target.checked ? [...preferences.columns, column.key] : preferences.columns.filter(key => key !== column.key) })} />{column.label}</label>)}</div></details>
          {rows.length ? <AssetTable rows={visibleRows} columns={columns} watched={preferences.watched} caption={`${category.label} ${mode === 'demo' ? '虚构演示' : mode === 'market' ? '市场行情' : '导入研究'}清单`} onSelect={row => setSelectedCode(row.code)} onWatch={code => update({ ...preferences, watched: preferences.watched.includes(code) ? preferences.watched.filter(item => item !== code) : [...preferences.watched, code] })} /> : <EmptyState title="没有符合筛选条件的标的" hint="可清空搜索，或关闭“只看自选”查看完整清单。" />}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-[11px] text-muted"><span>筛选 {rows.length} / 共 {snapshot.data.rows.length} 条 · 每页 50 条 · 自选仅保存在当前浏览器</span>{lastPage > 0 && <div className="flex items-center gap-2"><button type="button" className={BUTTON} disabled={page === 0} onClick={() => setPageIndex(page - 1)}>上一页</button><span>{page + 1} / {lastPage + 1}</span><button type="button" className={BUTTON} disabled={page === lastPage} onClick={() => setPageIndex(page + 1)}>下一页</button></div>}</div>
        </>}
      </>}
    </section>
    {showImport && canImport && snapshot.data && <ImportPanel category={category} snapshot={snapshot.data} onClose={() => setShowImport(false)} onSaved={onSaved} onReload={onReload} onTemplate={() => void download('template')} />}
    {selectedRow && <AssetDetail category={category} row={selectedRow} onClose={() => setSelectedCode(null)} />}
    <section className="rounded-card border border-border bg-surface p-4"><h3 className="text-xs font-medium text-secondary">{category.label} · 使用口径</h3><ul className="mt-2 list-inside list-disc space-y-1.5 text-[11px] leading-relaxed text-muted">{category.notes.map((note, index) => <li key={index}>{note}</li>)}</ul></section>
  </div>
}
