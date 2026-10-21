// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ConvertibleDataset } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ConvertiblesPage } from './ConvertiblesPage'

const mocks = vi.hoisted(() => ({ load: vi.fn(), imported: null as ConvertibleDataset | null }))
vi.mock('@/lib/api', () => ({ api: { convertibles: mocks.load } }))
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
  await click('刷新')
  await click('导入 CSV')
  await click('模拟成功导入')
  expect(host.textContent).toContain('新导入快照')
  await act(async () => resolveOld(old))
  await settle()
  expect(host.textContent).toContain('新导入快照')
  expect(host.textContent).not.toContain('旧研究快照')
  expect(client.getQueryData<ConvertibleDataset>(QK.convertibles)?.revision).toBe('new')
})
