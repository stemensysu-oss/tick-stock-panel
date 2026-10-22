// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { FundNavResponse } from '@/lib/api'
import { FundsPage } from './FundsPage'

const mocks = vi.hoisted(() => ({
  status: vi.fn(), profile: vi.fn(), nav: vi.fn(), holdings: vi.fn(), trading: vi.fn(), dividends: vi.fn(),
  pending: [] as { range: string; resolve: (value: FundNavResponse) => void }[],
}))
vi.mock('@/lib/api', () => ({ api: {
  fundResearchStatus: mocks.status, fundProfile: mocks.profile, fundNav: mocks.nav, fundHoldings: mocks.holdings,
  fundTrading: mocks.trading, fundDividends: mocks.dividends,
} }))
vi.mock('./FundNavChart', async importOriginal => ({
  ...await importOriginal<typeof import('./FundNavChart')>(),
  FundNavChart: ({ items }: { items: { date: string }[] }) => <div data-chart>{items.map(item => item.date).join(',')}</div>,
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks()
  mocks.pending.length = 0
  mocks.status.mockResolvedValue({ provider: 'fuyao', configured: true, permission_status: 'unverified', capabilities: ['profile', 'nav', 'holdings'], message: '已配置' })
  mocks.profile.mockImplementation(async (ticker: string) => ({ ticker, provider: 'fuyao', timestamp_ms: null, profile: { fund_name: `基金${ticker}`, mgmt_name: null, manager_name: null, established_date: null, unit_nav: 1 } }))
  mocks.holdings.mockResolvedValue({ items: [], stock_ratio_pct: null, bond_ratio_pct: null, fund_ratio_pct: null })
  const unknownLimit = { status: 'unknown', value: null, unit: 'CNY', source_text: null }
  mocks.trading.mockResolvedValue({ subscription_status: '开放申购', redemption_status: '开放赎回', minimum_purchase: unknownLimit, daily_purchase_limit: unknownLimit, minimum_redemption: unknownLimit, minimum_remaining: unknownLimit })
  mocks.dividends.mockResolvedValue({ items: [] })
  mocks.nav.mockImplementation((_ticker: string, range: string) => new Promise<FundNavResponse>(resolve => mocks.pending.push({ range, resolve })))
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
})

afterEach(async () => {
  await act(async () => root.unmount())
  client.clear()
  host.remove()
})

async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function render() {
  await act(async () => root.render(<MemoryRouter><QueryClientProvider client={client}><FundsPage /></QueryClientProvider></MemoryRouter>))
  await settle()
}
async function enterTicker(value: string) {
  const input = host.querySelector<HTMLInputElement>('#fund-ticker')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await settle()
}

it('未配置数据源时禁用查询，不调用付费数据接口', async () => {
  mocks.status.mockResolvedValue({ configured: false, message: '请配置 FUYAO_API_KEY' })
  await render()
  expect(host.textContent).toContain('请配置 FUYAO_API_KEY')
  expect(host.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true)
  expect(mocks.profile).not.toHaveBeenCalled()
  expect(mocks.nav).not.toHaveBeenCalled()
  expect(mocks.holdings).not.toHaveBeenCalled()
})

it('首次自动查询示例基金；切换代码和区间后迟到响应不会冒充当前数据', async () => {
  await render()
  expect(mocks.nav).toHaveBeenCalledWith('510300.SH', 'year')
  // 慢速历史序列不应阻止用户搜索另一只基金。
  expect(host.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(false)
  mocks.pending.length = 0
  await enterTicker('000001.of')
  expect(mocks.nav).toHaveBeenCalledWith('000001.OF', 'year')
  const monthButton = [...host.querySelectorAll('button')].find(button => button.textContent === '近一月')!
  await act(async () => monthButton.click())
  await settle()
  await act(async () => mocks.pending.find(call => call.range === 'year')!.resolve({ ticker: '000001.OF', provider: 'fuyao', timestamp_ms: null, range: 'year', items: [{ date: '2025-10-01', unit_nav: 1, adj_nav: null }] }))
  await settle()
  expect(host.querySelector('[data-chart]')).toBeNull()
  await act(async () => mocks.pending.find(call => call.range === 'month')!.resolve({ ticker: '000001.OF', provider: 'fuyao', timestamp_ms: null, range: 'month', items: [{ date: '2026-10-01', unit_nav: 1.2, adj_nav: null }] }))
  await settle()
  expect(host.querySelector('[data-chart]')?.textContent).toBe('2026-10-01')
  expect(host.textContent).not.toContain('2025-10-01')
})

it('刷新状态涵盖申赎和分红，慢数据集仍在读取时不可重复刷新', async () => {
  mocks.nav.mockResolvedValue({ items: [{ date: '2026-10-21', unit_nav: 1.2, adj_nav: null }] })
  let finish!: (value: { items: [] }) => void
  mocks.dividends.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  await render()
  const refresh = [...host.querySelectorAll('button')].find(button => button.textContent === '刷新')!
  expect(refresh.disabled).toBe(true)
  expect(host.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(false)
  await act(async () => finish({ items: [] }))
  await settle()
  expect(refresh.disabled).toBe(false)
})

it('后台刷新失败保留基金资料、净值、持仓、申赎和分红的有效快照', async () => {
  mocks.nav.mockResolvedValue({ series_kind: 'nav', items: [{ date: '2026-10-21', unit_nav: 1.2, adj_nav: null }] })
  mocks.holdings.mockResolvedValue({ items: [{ ticker: '600000.SH', name: '已披露股票', asset_type: 'stock', weight_pct: 4, report_date: '2026-06-30', publish_date: null }] })
  mocks.dividends.mockResolvedValue({ items: [{ per_ten_cash_before_tax: 1.2345 }] })
  await render()
  for (const request of [mocks.profile, mocks.nav, mocks.holdings, mocks.trading, mocks.dividends]) request.mockRejectedValue(new Error('补充源超时'))
  await act(async () => [...host.querySelectorAll('button')].find(button => button.textContent === '刷新')!.click())
  await settle()
  expect(host.textContent).toContain('基金510300.SH')
  expect(host.querySelector('[data-chart]')?.textContent).toBe('2026-10-21')
  expect(host.textContent).toContain('已披露股票')
  expect(host.textContent).toContain('开放申购')
  expect(host.textContent).toContain('1.2345')
  expect(host.textContent).toContain('刷新失败，保留上次结果')
})

it('货币基金在加载、空收益与错误状态中不称为净值', async () => {
  mocks.profile.mockResolvedValue({ profile: { fund_name: '货币基金', series_kind: 'money' } })
  await render()
  expect(host.textContent).toContain('正在读取货币基金历史收益')
  await act(async () => mocks.pending[0].resolve({ ticker: '510300.SH', provider: 'eastmoney_public', timestamp_ms: null, range: 'year', series_kind: 'money', items: [] }))
  await settle()
  expect(host.textContent).toContain('所选区间暂无该口径收益')
  expect(host.textContent).not.toContain('切换单位净值')
  mocks.nav.mockRejectedValue(new Error('货币收益接口超时'))
  await enterTicker('000009.OF')
  expect(host.textContent).toContain('历史收益读取失败')
  expect(host.textContent).not.toContain('历史净值读取失败')
})

it('持仓类型与报告期切换时隔离缓存和迟到响应', async () => {
  mocks.nav.mockResolvedValue({ items: [] })
  const requests: { asset: string; period: string; resolve: (value: unknown) => void }[] = []
  mocks.holdings.mockImplementation((_ticker, asset, period) => new Promise(resolve => requests.push({ asset, period, resolve })))
  await render()
  const select = host.querySelector<HTMLSelectElement>('[aria-label="持仓类型"]')!
  await act(async () => { select.value = 'bond'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await settle()
  const period = host.querySelector<HTMLSelectElement>('[aria-label="持仓报告期"]')!
  const historical = period.options[1].value
  await act(async () => { period.value = historical; period.dispatchEvent(new Event('change', { bubbles: true })) })
  await settle()
  await act(async () => requests.find(request => request.asset === 'stock')!.resolve({ items: [{ ticker: '600000.SH', name: '迟到旧股票', asset_type: 'stock' }] }))
  await settle()
  expect(host.textContent).not.toContain('迟到旧股票')
  await act(async () => requests.find(request => request.asset === 'bond' && request.period === historical)!.resolve({ items: [{ ticker: '019000.SH', name: '所选历史债券', asset_type: 'bond', report_date: historical }] }))
  await settle()
  expect(host.textContent).toContain('所选历史债券')
  expect(mocks.holdings).toHaveBeenCalledWith('510300.SH', 'bond', historical)
})

it('明确未确认收益口径时不把返回数字展示成净值曲线', async () => {
  mocks.nav.mockResolvedValue({ series_kind: 'unknown', items: [{ date: '2026-10-21', unit_nav: 0.31, adj_nav: null }] })
  await render()
  expect(host.textContent).toContain('尚未确认收益口径')
  expect(host.querySelector('[data-chart]')).toBeNull()
})
