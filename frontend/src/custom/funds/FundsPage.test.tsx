// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { FundNavResponse } from '@/lib/api'
import { FundsPage } from './FundsPage'

const mocks = vi.hoisted(() => ({
  status: vi.fn(), profile: vi.fn(), nav: vi.fn(), holdings: vi.fn(),
  pending: [] as { range: string; resolve: (value: FundNavResponse) => void }[],
}))
vi.mock('@/lib/api', () => ({ api: {
  fundResearchStatus: mocks.status, fundProfile: mocks.profile, fundNav: mocks.nav, fundHoldings: mocks.holdings,
} }))
vi.mock('./FundNavChart', () => ({ FundNavChart: ({ items }: { items: { date: string }[] }) => <div data-chart>{items.map(item => item.date).join(',')}</div> }))

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

it('未选择基金不查询；切换区间后迟到响应不会冒充当前区间数据', async () => {
  await render()
  expect(mocks.nav).not.toHaveBeenCalled()
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
