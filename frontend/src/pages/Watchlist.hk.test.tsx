// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Watchlist } from './Watchlist'

const mocks = vi.hoisted(() => ({
  search: vi.fn(), list: vi.fn(), add: vi.fn(), enriched: vi.fn(), hk: vi.fn(),
  daily: vi.fn(), minute: vi.fn(), preview: vi.fn(), auction: vi.fn(), stats: vi.fn(),
  entries: [] as any[], mainland: [] as any[],
}))
vi.mock('@/lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { ...actual.api,
    instrumentSearch: mocks.search, watchlistList: mocks.list, watchlistAdd: mocks.add,
    watchlistEnriched: mocks.enriched, watchlistHkQuotes: mocks.hk, klineDailyBatch: mocks.daily,
    watchlistGroups: async () => ({ groups: [{ id: 'g1', name: '观察组', color: 'blue' }] }),
  } }
})
vi.mock('@/lib/useSharedQueries', () => ({
  useCapabilities: () => ({ data: { capabilities: { 'kline.minute.batch': true } } }),
  useQuoteStatus: () => ({ data: { running: false } }),
  usePreferences: () => ({ data: {} }),
}))
vi.mock('@/lib/minuteBatchIncremental', () => ({ fetchMinuteBatchIncremental: mocks.minute }))
vi.mock('@/lib/watchlist-columns', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/watchlist-columns')>()
  return { ...actual, loadColumnConfig: async () => actual.BUILTIN_COLUMNS.map(column =>
    column.source.type === 'builtin' && ['candle', 'intraday'].includes(column.source.key)
      ? { ...column, visible: true } : column) }
})
vi.mock('@/lib/intraday-auction', () => ({ useAuctionConfig: () => null, useAuctionSeries: (_: unknown, symbols: string[]) => { mocks.auction(symbols); return {} } }))
vi.mock('@/components/StockPreviewDialog', () => ({ StockPreviewDialog: (props: any) => { mocks.preview(props); return props.symbol ? <div data-mainland-preview>{props.symbol}</div> : null } }))
vi.mock('@/components/ColumnCustomizer', () => ({ ColumnCustomizer: () => null }))
vi.mock('@/components/WatchlistImportDialog', () => ({ WatchlistImportDialog: () => null }))
vi.mock('@/extensions/ExtensionSlot', () => ({ ExtensionSlot: () => null }))
vi.mock('@/components/stock-table/MiniCandlestick', () => ({ MiniCandlestick: () => <div data-daily-chart /> }))
vi.mock('@/components/stock-table/MiniIntraday', () => ({ MiniIntraday: () => <div data-minute-chart /> }))
vi.mock('@/components/WatchlistGroupStatsBar', () => ({ WatchlistGroupStatsBar: (props: any) => { mocks.stats(props.pcts); return <div data-group-stats /> } }))
vi.mock('@/components/WatchlistGroups', () => ({
  WatchlistGroupBar: () => null,
  WatchlistGroupPicker: () => null,
}))

let host: HTMLDivElement, root: Root, client: QueryClient
const hkQuote = { symbol: '00700.HK', name: '腾讯控股', asset_type: 'hk', currency: 'HKD',
  close: 512.5, change_pct: 0.0125, quote_at: '2026-10-22T15:01:00+08:00',
  quote_source: 'tencent_public', quote_status: 'available', quote_warnings: ['公开港股行情可能延迟'] }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks(); localStorage.clear(); mocks.entries = []; mocks.mainland = []
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => setTimeout(() => fn(0), 0))
  vi.stubGlobal('cancelAnimationFrame', clearTimeout)
  mocks.list.mockImplementation(async () => ({ symbols: mocks.entries }))
  mocks.add.mockImplementation(async (symbol, _note, groupId) => {
    mocks.entries = [...mocks.entries, { symbol, group_ids: groupId ? [groupId] : [] }]
    return { symbols: mocks.entries }
  })
  mocks.search.mockResolvedValue({ results: [
    { symbol: '00700.HK', code: '00700', name: '腾讯控股', asset_type: 'hk', currency: 'HKD' },
    { symbol: '600700.SH', code: '600700', name: '另一只内地股票', asset_type: 'stock' },
  ] })
  mocks.enriched.mockImplementation(async () => ({ rows: [
    ...mocks.mainland, ...mocks.entries.filter(entry => entry.symbol.endsWith('.HK')).map(entry => ({
      ...entry, name: '腾讯控股', asset_type: 'hk', currency: null, close: null, change_pct: null,
    })),
  ], as_of: '2026-10-22', elapsed_ms: 0 }))
  mocks.hk.mockResolvedValue({ rows: [hkQuote], attempts: [], warnings: [], status: 'available', fetched_at: hkQuote.quote_at })
  mocks.daily.mockResolvedValue({ data: {} }); mocks.minute.mockResolvedValue({ data: {} })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.unstubAllGlobals() })
async function settle() { for (let i = 0; i < 8; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
async function render(url = '/watchlist') {
  await act(async () => root.render(<MemoryRouter initialEntries={[url]}><QueryClientProvider client={client}><Watchlist /></QueryClientProvider></MemoryRouter>))
  await settle()
}
async function search(query: string) {
  const input = host.querySelector<HTMLInputElement>('[aria-label="搜索内地或港股代码及名称"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, query)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }); await settle()
}
async function click(label: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => item.getAttribute('aria-label') === label || item.title === label || item.textContent?.trim() === label)
  expect(button, label).toBeTruthy(); await act(async () => button!.click()); await settle()
}

it('00700 searches Hong Kong and adds the exact HK code to the active group', async () => {
  await render('/watchlist?group=g1'); await search('00700')
  expect(mocks.search).toHaveBeenLastCalledWith('00700', 20, 'stock,etf,index,hk')
  expect(host.textContent).toContain('腾讯控股'); expect(host.textContent).toContain('港股')
  await click('快速加入自选 00700.HK')
  expect(mocks.add).toHaveBeenLastCalledWith('00700.HK', '', 'g1')
  expect(mocks.add).not.toHaveBeenCalledWith('600700.SH', expect.anything(), expect.anything())
  expect(host.textContent).toContain('512.50'); expect(host.textContent).toContain('+1.25%')
  expect(mocks.daily).not.toHaveBeenCalled(); expect(mocks.minute).not.toHaveBeenCalled()
})

it('search preview can add HK but never opens the A-share preview or charts', async () => {
  await render(); await search('腾讯科技')
  const result = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('00700.HK') && button.textContent?.includes('腾讯控股'))!
  await act(async () => result.click()); await settle()
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('尚无有效报价时点')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('币种待报价确认')
  await click('加入当前自选分组并获取报价')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('512.50')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('HKD 港元')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain(hkQuote.quote_at)
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('腾讯公开补充行情')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('历史 K 线、分时、技术指标和分析尚未接入')
  expect(mocks.preview.mock.calls.some(([props]) => props.symbol === '00700.HK')).toBe(false)
  expect(mocks.daily).not.toHaveBeenCalled(); expect(mocks.minute).not.toHaveBeenCalled()
  expect(host.querySelector('[data-mainland-preview]')).toBeNull()
})

it('mixed watchlist keeps mainland charts and excludes HK from A-share requests and group performance', async () => {
  mocks.entries = [{ symbol: '00700.HK', group_ids: [] }, { symbol: '600000.SH', group_ids: [] }]
  mocks.mainland = [{ symbol: '600000.SH', name: '浦发银行', asset_type: 'stock', close: 10, change_pct: 0.02 }]
  await render()
  expect(mocks.daily).toHaveBeenCalledWith(['600000.SH'], expect.any(Number))
  expect(mocks.minute).toHaveBeenCalled()
  expect(mocks.minute.mock.calls.every(([, , symbols]) => JSON.stringify(symbols) === '["600000.SH"]')).toBe(true)
  expect(mocks.auction.mock.calls.every(([symbols]) => !symbols.includes('00700.HK'))).toBe(true)
  expect(host.textContent).toContain('港股未接入')
  await click('分组统计')
  expect(mocks.stats.mock.calls.at(-1)?.[0].all.pct).toBe(0.02)
  const mainland = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('600000.SH') && button.textContent?.includes('浦发银行'))!
  await act(async () => mainland.click()); await settle()
  const props = mocks.preview.mock.calls.at(-1)?.[0]
  expect(props.symbol).toBe('600000.SH'); expect(props.navList.map((item: any) => item.symbol)).toEqual(['600000.SH'])
})

it('HK manual refresh is forced and a failure keeps the last genuine quote visible', async () => {
  mocks.entries = [{ symbol: '00700.HK', group_ids: [] }]
  await render()
  const row = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('00700.HK') && button.textContent?.includes('腾讯控股'))!
  await act(async () => row.click()); await settle()
  mocks.hk.mockRejectedValueOnce(new Error('补充源暂不可用'))
  await click('刷新港股报价')
  expect(mocks.hk).toHaveBeenLastCalledWith(true)
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('512.50')
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('保留上次有效报价')
  expect(host.textContent).toContain('补充源暂不可用')
})

it('HK card shows currency and excludes mainland technical signals and mini charts', async () => {
  localStorage.setItem('watchlist_view', JSON.stringify('card'))
  mocks.entries = [{ symbol: '00700.HK', group_ids: [] }]
  mocks.hk.mockResolvedValueOnce({ rows: [{ ...hkQuote, rsi_14: 88, consecutive_limit_ups: 2 }], attempts: [], warnings: [], status: 'available' })
  await render()
  expect(host.textContent).toContain('港股 · HKD')
  expect(host.textContent).toContain('港元报价 · 技术指标未接入')
  expect(host.textContent).not.toContain('2连')
  expect(host.querySelector('[data-daily-chart]')).toBeNull()
  expect(host.querySelector('[data-minute-chart]')).toBeNull()
  expect(mocks.daily).not.toHaveBeenCalled(); expect(mocks.minute).not.toHaveBeenCalled()
})

it('failed HK search is retryable without silently adding a mainland substring match', async () => {
  mocks.search.mockRejectedValueOnce(new Error('港股目录暂不可用'))
  await render(); await search('00700')
  expect(host.textContent).toContain('港股目录暂不可用')
  expect(mocks.add).not.toHaveBeenCalled()
  await click('重试搜索')
  expect(host.textContent).toContain('腾讯控股')
  expect(mocks.search).toHaveBeenLastCalledWith('00700', 20, 'stock,etf,index,hk')
})

it('an empty search response discloses provider warnings and can retry without a fake quote', async () => {
  mocks.search.mockResolvedValueOnce({ results: [], warnings: ['港股搜索补充源未返回有效结果，请稍后重试。'] })
  await render(); await search('00700')
  expect(host.textContent).toContain('港股搜索补充源未返回有效结果')
  expect(host.textContent).not.toContain('512.50')
  expect(mocks.add).not.toHaveBeenCalled()
  await click('重新搜索')
  expect(host.textContent).toContain('腾讯控股')
})
