// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type HkFundamentals } from '@/lib/api'
import { HkFinancialStatements } from './HkFinancialStatements'

let root: Root, host: HTMLDivElement, client: QueryClient
const data: HkFundamentals = { symbol: '00700.HK', status: 'available', fetched_at: '2026-10-24', warnings: ['财报币种独立于股价'], references: [], tables: { income: { label: '利润表', status: 'available', source: 'eastmoney_public', source_url: 'https://emweb.securities.eastmoney.com/', reports: [{ period_end: '2026-06-30', period_start: '2026-01-01', announce_date: null, report_type: '中报', currency: 'CNY', items: [{ code: '004001999', name: '营运收入', value: 401243000000, unit: 'base_currency' }] }] } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.restoreAllMocks() })
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><HkFinancialStatements symbol="00700.HK" /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) })
}
it('shows actual report currency, period, source, values and unknown disclosure date', async () => {
  vi.spyOn(api, 'hkFundamentals').mockResolvedValue(data)
  await render()
  expect(host.textContent).toContain('CNY')
  expect(host.textContent).toContain('401,243,000,000')
  expect(host.textContent).toContain('未知，不能用报告期替代')
  expect(host.textContent).toContain('东方财富公开补充源')
  expect(host.textContent).not.toContain('HKD 元')
})
it('keeps the last good statement visible when a forced refresh fails', async () => {
  const read = vi.spyOn(api, 'hkFundamentals').mockResolvedValueOnce(data)
  await render()
  read.mockRejectedValue(new Error('offline'))
  await act(async () => host.querySelector('button')!.click())
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) })
  expect(host.textContent).toContain('已有资料保留')
  expect(host.textContent).toContain('401,243,000,000')
})
