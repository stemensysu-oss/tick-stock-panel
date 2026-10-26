// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ConvertibleDataset } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ConvertiblesPage } from './ConvertiblesPage'

const mocks = vi.hoisted(() => ({ load: vi.fn(), status: vi.fn(), refresh: vi.fn(), references: vi.fn(), imported: null as ConvertibleDataset | null }))
vi.mock('@/lib/api', () => ({ api: { convertibles: mocks.load, convertibleSourceStatus: mocks.status, refreshConvertibles: mocks.refresh, calculateConvertibles: mocks.references } }))
vi.mock('@/components/Toast', () => ({ toast: vi.fn() }))
vi.mock('./ImportPanel', () => ({ ImportPanel: ({ onSaved }: { onSaved: (dataset: ConvertibleDataset) => Promise<void> }) => <button onClick={() => void onSaved(mocks.imported!)}>模拟成功导入</button> }))

function snapshot(revision: string, name: string): ConvertibleDataset {
  return { revision, as_of: '2026-10-20', updated_at: null, source: '用户导入', items: [{
    code: '100001', name, stock_code: null, stock_name: null, bond_price: 110,
    stock_price: 10, conversion_price: 10, face_value: 100, maturity_date: null,
    redemption_status: null, conversion_value: 100, conversion_premium_pct: 10, double_low: 120,
  }] }
}

let host: HTMLDivElement
let root: Root
let client: QueryClient
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks()
  window.localStorage.clear()
  mocks.references.mockImplementation(async (revision: string) => ({ revision, references: [], attempts: [], warnings: [] }))
  mocks.status.mockResolvedValue({ provider: 'tickflow', configured: false, mode: 'unconfigured', message: '请配置行情 Key', capabilities: { quotes: true, terms: false, announcements: false }, last_refresh_at: null })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove() })
async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(item => item.textContent === text)!
  await act(async () => button.click())
  await settle()
}

it('保存前开始的迟到读取不会覆盖已导入的新快照', async () => {
  const old = snapshot('old', '旧研究快照')
  mocks.imported = snapshot('new', '新导入快照')
  mocks.load.mockResolvedValueOnce(old)
  let resolveOld!: (value: ConvertibleDataset) => void
  mocks.load.mockImplementationOnce(() => new Promise<ConvertibleDataset>(resolve => { resolveOld = resolve }))
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  await click('重新载入')
  await click('导入 CSV')
  await click('模拟成功导入')
  expect(host.textContent).toContain('新导入快照')
  await act(async () => resolveOld(old))
  await settle()
  expect(host.textContent).toContain('新导入快照')
  expect(host.textContent).not.toContain('旧研究快照')
  expect(client.getQueryData<ConvertibleDataset>(QK.convertibles)?.revision).toBe('new')
})


it('没有行情Key时仍可尝试补充源，保留CSV研究功能', async () => {
  mocks.load.mockResolvedValue(snapshot('base', '仍可研究的转债'))
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  const update = [...host.querySelectorAll('button')].find(button => button.textContent === '更新行情')!
  expect(update.disabled).toBe(false)
  expect(host.textContent).toContain('行情 Key 未配置')
  expect(host.textContent).toContain('仍可研究的转债')
  expect(mocks.refresh).not.toHaveBeenCalled()
})

it('空清单自动获取一次市场列表，失败可手动重试且不会反复请求', async () => {
  mocks.load.mockResolvedValue({ revision: '0', as_of: null, updated_at: null, source: '用户导入', items: [] })
  mocks.refresh.mockRejectedValueOnce(new Error('补充源超时'))
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  expect(mocks.refresh).toHaveBeenCalledTimes(1)
  expect(host.textContent).toContain('补充源超时')
  mocks.refresh.mockResolvedValueOnce(snapshot('market-1', '网络获取的测试转债'))
  await click('获取市场清单')
  expect(mocks.refresh).toHaveBeenCalledTimes(2)
  expect(host.textContent).toContain('网络获取的测试转债')
})

it('行情更新失败保留已保存清单，并显示明确错误原因', async () => {
  mocks.load.mockResolvedValue(snapshot('base', '保留的有效快照'))
  mocks.status.mockResolvedValue({ provider: 'tickflow', configured: true, mode: 'realtime', message: '已配置，权限待验证', capabilities: { quotes: true, terms: false, announcements: false }, last_refresh_at: null })
  mocks.refresh.mockRejectedValue(new Error('当前 Key 没有可转债权限'))
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  await click('更新行情')
  expect(mocks.refresh).toHaveBeenCalledWith({ expected_revision: 'base' }, expect.anything())
  expect(host.textContent).toContain('当前 Key 没有可转债权限')
  expect(host.textContent).toContain('保留的有效快照')
  expect(client.getQueryData<ConvertibleDataset>(QK.convertibles)?.revision).toBe('base')
})

it('勾选两只可逐项对比，并可切换散点图打开同一研究集', async () => {
  const data = snapshot('base', '甲转债')
  data.items.push({ ...data.items[0], code: '100002', name: '乙转债', bond_price: 120, conversion_premium_pct: 20, double_low: 140 })
  mocks.load.mockResolvedValue(data)
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  await act(async () => { host.querySelector<HTMLInputElement>('[aria-label="对比 甲转债"]')!.click(); host.querySelector<HTMLInputElement>('[aria-label="对比 乙转债"]')!.click() })
  await settle()
  await click('对比已选 2 只')
  expect(host.textContent).toContain('研究指标')
  expect(host.textContent).toContain('120.000')
  expect([...host.querySelectorAll('button')].filter(button => button.textContent === '移出对比')).toHaveLength(2)
  await click('散点图')
  expect(host.querySelectorAll('circle[role="button"]')).toHaveLength(2)
})

it('打开已有清单自动补齐纯债及到期日，排序显示使用参考但不改写原快照', async () => {
  const raw = snapshot('base', '已有研究转债')
  mocks.load.mockResolvedValue(raw)
  mocks.references.mockResolvedValue({ revision: 'base', items: raw.items, references: [{ code: '100001.SH', pure_bond_value: 98.7654, valuation_date: '2026-10-23', maturity_date: '2027-12-27', credit_rating: 'AAA', warnings: [] }], attempts: [], warnings: ['公开模型参考'] })
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertiblesPage /></QueryClientProvider>))
  await settle()
  expect(mocks.references).toHaveBeenCalledWith('base')
  expect(host.textContent).toContain('98.77')
  expect(host.textContent).toContain('公开模型参考')
  expect(host.textContent).toContain('2026-10-23')
  expect(host.textContent).toContain('2027-12-27')
  expect(client.getQueryData<ConvertibleDataset>(QK.convertibles)?.items[0].maturity_date).toBeNull()
  mocks.references.mockRejectedValueOnce(new Error('参考源暂不可用'))
  await click('补齐条款与估值')
  expect(host.textContent).toContain('参考源暂不可用')
  expect(host.textContent).toContain('98.77')
})
