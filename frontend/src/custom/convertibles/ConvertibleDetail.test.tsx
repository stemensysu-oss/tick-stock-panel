// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError, type ConvertibleItem, type ConvertibleResearch } from '@/lib/api'
import { ConvertibleDetail } from './ConvertibleDetail'
import { buildResearch, createResearchDraft } from './researchForm'

const mocks = vi.hoisted(() => ({ analyze: vi.fn(), save: vi.fn(), saved: vi.fn(), disclosures: vi.fn() }))
vi.mock('@/lib/api', () => ({
  ApiError: class extends Error { constructor(message: string, readonly status: number) { super(message) } },
  api: { previewConvertibleCalculation: mocks.analyze, saveConvertibleResearch: mocks.save, convertibleDisclosures: mocks.disclosures },
}))
let host: HTMLDivElement
let root: Root
let client: QueryClient
const item: ConvertibleItem = { code: '123001.SZ', name: '现金流测试转债', stock_code: '300001.SZ', stock_name: '示例正股', bond_price: 110, stock_price: 10, conversion_price: 10, face_value: 100, maturity_date: '2027-10-21', redemption_status: null, conversion_value: 100, conversion_premium_pct: 10, double_low: 120 }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(0), 0))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  mocks.analyze.mockResolvedValue({ items: [{ ...item, ytm_pct: 5 }] })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.unstubAllGlobals() })
async function settle() { for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
async function click(text: string) { const button = [...host.querySelectorAll('button')].find(element => element.textContent === text)!; await act(async () => button.click()); await settle() }
async function fill(label: string, value: string) {
  const field = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!
  await act(async () => { const prototype = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true })) })
}
async function render(research?: ConvertibleResearch) {
  await act(async () => root.render(<QueryClientProvider client={client}><ConvertibleDetail item={{ ...item, research }} revision="revision-1" asOf="2026-10-21" source="用户导入" onClose={() => {}} onSaved={mocks.saved} watched={false} hidden={false} onWatch={() => {}} onHide={() => {}} /></QueryClientProvider>))
  await settle()
}
it('试算不写入，保存携带打开时版本；冲突不会清空表单或允许直接覆盖', async () => {
  const research = buildResearch(createResearchDraft()); research.price_basis = 'full'
  research.cash_flows = [{ date: '2027-10-21', amount: 110 }]; research.cash_flows_complete = true
  await render(research)
  await click('现金流与估值')
  await fill('纯债折现率（%）', '3')
  await click('试算')
  expect(mocks.analyze).toHaveBeenCalledWith('123001.SZ', 'revision-1', expect.objectContaining({ discount_rate_pct: 3, price_basis: 'full', cash_flows_complete: true }))
  expect(mocks.save).not.toHaveBeenCalled()
  expect(host.textContent).toContain('本次试算结果')
  mocks.save.mockRejectedValue(new ApiError('版本冲突', 409))
  await click('保存研究资料')
  expect(mocks.save).toHaveBeenCalledWith('123001.SZ', expect.objectContaining({ expected_revision: 'revision-1' }))
  expect(host.textContent).toContain('版本冲突')
  expect((host.querySelector('[aria-label="纯债折现率（%）"]') as HTMLInputElement).value).toBe('3')
  await fill('纯债折现率（%）', '4')
  expect([...host.querySelectorAll('button')].find(button => button.textContent === '保存研究资料')!.disabled).toBe(true)
  expect(mocks.saved).not.toHaveBeenCalled()
})
it('调整条款数值不自动把昨日观察完整性确认更新到今天', async () => {
  const research = buildResearch(createResearchDraft())
  research.observations_as_of = '2026-10-20'
  research.call_clause = { window_days: 30, required_days: 15, trigger_ratio_pct: 130, consecutive: false, observations_complete: true, start_date: null, end_date: null, paused_until: null }
  await render(research)
  await click('条款观察')
  await fill('强赎触发比例', '135')
  await click('试算')
  expect(mocks.analyze).toHaveBeenCalledWith('123001.SZ', 'revision-1', expect.objectContaining({ observations_as_of: '2026-10-20', call_clause: expect.objectContaining({ trigger_ratio_pct: 135, observations_complete: false }) }))
})

it('试算版本冲突清除旧试算结果并禁止保存，防止误用另一个行情日', async () => {
  await render()
  await click('现金流与估值')
  await fill('纯债折现率（%）', '3')
  await click('试算')
  expect(host.textContent).toContain('本次试算结果')
  mocks.analyze.mockRejectedValue(new ApiError('行情数据已变化，请重新载入', 409))
  await click('试算')
  expect(host.textContent).not.toContain('本次试算结果')
  expect(host.textContent).toContain('研究清单已更新')
  expect([...host.querySelectorAll('button')].find(button => button.textContent === '保存研究资料')!.disabled).toBe(true)
})

it('联网条款入口可达、读取所选代码且保留人工编辑', async () => {
  mocks.disclosures.mockResolvedValue({ code: item.code, lifecycle: 'listed', call_state: 'unknown',
    fetched_at: '2026-10-22T10:00:00+08:00', call_clause_text: '合成条款原文', events: [], warnings: [], attempts: [] })
  await render()
  await click('现金流与估值')
  await fill('纯债折现率（%）', '3')
  await click('联网条款与强赎')
  expect(mocks.disclosures).toHaveBeenCalledWith(item.code)
  expect(host.textContent).toContain('合成条款原文')
  expect(host.textContent).toContain('未确认实施状态')
  expect([...host.querySelectorAll('button')].some(button => button.textContent === '试算')).toBe(false)
  expect([...host.querySelectorAll('button')].some(button => button.textContent === '保存研究资料')).toBe(false)
  expect(host.textContent).toContain('联网资料只读')
  expect(mocks.save).not.toHaveBeenCalled()
  await click('现金流与估值')
  expect((host.querySelector('[aria-label="纯债折现率（%）"]') as HTMLInputElement).value).toBe('3')
})

it('联网条款刷新失败保留已读取原文，仍提示未保存人工资料', async () => {
  mocks.disclosures.mockResolvedValue({ code: item.code, lifecycle: 'listed', call_state: 'unknown',
    fetched_at: '2026-10-22T10:00:00+08:00', call_clause_text: '先前读取的真实条款', events: [], warnings: [], attempts: [] })
  await render()
  await click('现金流与估值')
  await fill('纯债折现率（%）', '4')
  await click('联网条款与强赎')
  mocks.disclosures.mockRejectedValue(new Error('公开源超时'))
  await click('重新读取')
  expect(host.textContent).toContain('先前读取的真实条款')
  expect(host.textContent).toContain('刷新失败，保留上次结果')
  expect(host.textContent).toContain('人工研究有未保存修改')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="关闭转债详情"]')!.click())
  await settle()
  expect(host.textContent).toContain('关闭会丢弃本次编辑')
  expect(mocks.save).not.toHaveBeenCalled()
})
