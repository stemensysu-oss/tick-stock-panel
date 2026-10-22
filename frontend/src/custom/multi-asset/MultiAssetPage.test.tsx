// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError, type MultiAssetCatalog, type MultiAssetSnapshot } from '@/lib/api'
import { MultiAssetPage } from './MultiAssetPage'

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), snapshot: vi.fn(), preview: vi.fn(), save: vi.fn(), template: vi.fn(), export: vi.fn() }))
vi.mock('@/lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { multiAssetCatalog: mocks.catalog, multiAssetSnapshot: mocks.snapshot, previewMultiAssetImport: mocks.preview, importMultiAsset: mocks.save, multiAssetTemplate: mocks.template, exportMultiAsset: mocks.export } }
})

const catalog: MultiAssetCatalog = {
  schema_version: 1,
  categories: ['etf', 'new_category'].map((id, index) => ({
    id, label: index ? '动态新增类别' : 'ETF', description: '研究折溢价',
    fields: [{ key: 'code', label: '代码', type: 'text', required: true }],
    columns: [{ key: 'price', label: '价格', type: 'number', unit: '原币' }, { key: 'nav_premium_pct', label: '净值溢价率', type: 'number', unit: '%' }],
    notes: ['净值需要日期和币种一致'], planned_sources: ['交易所披露'], live_status: 'unavailable' as const,
  })), existing_modules: [{ label: '基金研究', path: '/funds' }],
}
function snapshot(mode: 'imported' | 'demo', category = 'etf', populated = false): MultiAssetSnapshot {
  return { schema_version: 1, category, mode, revision: mode === 'demo' ? 'demo' : 'rev-1', updated_at: null,
    data_status: mode === 'demo' ? 'demo' : populated ? 'imported' : 'empty', live_status: 'unavailable', warnings: [],
    rows: populated || mode === 'demo' ? [{ code: 'DEMO-001', name: mode === 'demo' ? '虚构示例 ETF' : '我的导入 ETF', currency: 'CNY', source_name: '测试来源', as_of: '2026-01-02', price: 1, data_status: mode, metrics: { nav_premium_pct: null }, warnings: [] }] : [],
  }
}
let host: HTMLDivElement
let root: Root
let client: QueryClient
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks()
  localStorage.clear()
  mocks.catalog.mockResolvedValue(catalog)
  mocks.snapshot.mockImplementation(async (category: string, mode: 'imported' | 'demo') => snapshot(mode, category))
  mocks.preview.mockResolvedValue({ ...snapshot('imported', 'etf', true), row_count: 1 })
  mocks.save.mockResolvedValue(snapshot('imported', 'etf', true))
  host = document.createElement('div'); document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove() })
async function settle() { for (let i = 0; i < 6; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
async function render(previewOnly = false) {
  await act(async () => root.render(<MemoryRouter><QueryClientProvider client={client}><MultiAssetPage previewOnly={previewOnly} /></QueryClientProvider></MemoryRouter>))
  await settle()
}
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find(item => item.textContent === label || item.getAttribute('aria-label') === label)
  expect(button, label).toBeTruthy()
  await act(async () => button!.click()); await settle()
}
async function fillCsv() {
  const area = host.querySelector('textarea')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, 'code,name,currency,source_name,as_of\nDEMO-001,测试,CNY,测试,2026-01-02')
    area.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await click('校验并预览')
}

it('首次使用默认空的导入数据，提供操作指引，类别由后端动态提供', async () => {
  await render()
  expect(mocks.snapshot).toHaveBeenCalledWith('etf', 'imported')
  expect(mocks.snapshot).not.toHaveBeenCalledWith('etf', 'demo')
  expect(host.textContent).toContain('开始建立 ETF 研究清单')
  expect(host.textContent).toContain('尚未接入实时行情')
  await click('动态新增类别')
  expect(mocks.snapshot).toHaveBeenCalledWith('new_category', 'imported')
})
it('演示切回导入后迟到的演示响应不会混入导入表格', async () => {
  let resolveDemo: (value: MultiAssetSnapshot) => void = () => {}
  mocks.snapshot.mockImplementation((category: string, mode: 'imported' | 'demo') => mode === 'demo' ? new Promise(resolve => { resolveDemo = resolve }) : Promise.resolve(snapshot(mode, category)))
  await render(); await click('虚构演示'); await click('我的导入数据')
  await act(async () => resolveDemo(snapshot('demo'))); await settle()
  expect(host.textContent).not.toContain('虚构示例 ETF')
  expect(host.textContent).toContain('开始建立 ETF 研究清单')
})
it('读取失败有重试提示，不用演示数据填充错误', async () => {
  mocks.snapshot.mockRejectedValue(new Error('服务连接失败'))
  await render()
  expect(host.textContent).toContain('服务连接失败')
  expect(host.textContent).not.toContain('开始建立 ETF 研究清单')
  expect(mocks.snapshot).not.toHaveBeenCalledWith('etf', 'demo')
})
it('只预览不写入；确认时携带版本，冲突后禁用确认并提供重新校验', async () => {
  mocks.save.mockRejectedValue(new ApiError('版本冲突', 409))
  await render(); await click('导入 CSV'); await fillCsv()
  expect(mocks.save).not.toHaveBeenCalled()
  expect(host.textContent).toContain('我的导入 ETF')
  await click('确认替换本类别清单')
  expect(mocks.save.mock.calls[0][0]).toEqual(expect.objectContaining({ category: 'etf', expected_revision: 'rev-1', confirmed: true }))
  expect(host.textContent).toContain('数据已被其他操作更新')
  expect([...host.querySelectorAll('button')].find(button => button.textContent === '确认替换本类别清单')!.disabled).toBe(true)
  await click('重新读取并校验')
  expect(mocks.snapshot.mock.calls.filter(call => call[1] === 'imported').length).toBeGreaterThan(1)
  expect(mocks.preview).toHaveBeenCalledTimes(2)
})
it('虚构演示显示来源、缺失值和独立的自选；预览模式没有写入入口', async () => {
  await render(true); await click('虚构演示')
  expect(host.textContent).toContain('单文件演示')
  expect(host.textContent).toContain('虚构示例 ETF')
  expect(host.textContent).toContain('--')
  expect([...host.querySelectorAll('button')].some(button => button.textContent === '导入 CSV')).toBe(false)
  expect(host.querySelector('a[href="/funds"]')).toBeNull()
})

it('校验失败不提供确认入口，修正文本后需要重新预览', async () => {
  mocks.preview.mockRejectedValueOnce(new ApiError('第 2 行缺少价格币种', 422))
  await render(); await click('导入 CSV'); await fillCsv()
  expect(host.textContent).toContain('第 2 行缺少价格币种')
  expect(host.textContent).not.toContain('确认替换本类别清单')
  expect(mocks.save).not.toHaveBeenCalled()
  await fillCsv()
  expect(host.textContent).toContain('确认替换本类别清单')
})

it('确认导入后取消早先读取，迟到旧快照不能覆盖已保存资料', async () => {
  await render(); await click('导入 CSV'); await fillCsv()
  let resolveOld: (value: MultiAssetSnapshot) => void = () => {}
  mocks.snapshot.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  mocks.snapshot.mockImplementation(async () => snapshot('imported', 'etf', true))
  await click('重新读取')
  await click('确认替换本类别清单')
  expect(host.textContent).toContain('已保存 1 条 ETF 导入资料')
  expect(host.textContent).toContain('我的导入 ETF')
  await act(async () => resolveOld(snapshot('imported'))); await settle()
  expect(host.textContent).toContain('我的导入 ETF')
  expect(host.textContent).not.toContain('开始建立 ETF 研究清单')
  expect(host.querySelector('textarea')).toBeNull()
})
