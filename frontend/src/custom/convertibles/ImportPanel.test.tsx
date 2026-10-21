// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { ImportPanel } from './ImportPanel'

const mocks = vi.hoisted(() => ({ preview: vi.fn(), save: vi.fn(), saved: vi.fn() }))
vi.mock('@/lib/api', () => ({
  ApiError: class extends Error { constructor(message: string, readonly status: number) { super(message) } },
  api: { previewConvertibles: mocks.preview, importConvertibles: mocks.save },
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient
const csv = 'code,name\n100001,测试转债'
const validPreview = { valid: true, total_rows: 1, items: [], errors: [], warnings: [], as_of: '2026-10-20', base_revision: 'revision-1' }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.resetAllMocks()
  mocks.preview.mockResolvedValue(validPreview)
  mocks.save.mockResolvedValue({ items: [] })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove() })

async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function fill(selector: string, value: string) {
  const input = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!
  await act(async () => {
    const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function start() {
  await act(async () => root.render(<QueryClientProvider client={client}><ImportPanel existingCount={3} onClose={() => {}} onSaved={mocks.saved} /></QueryClientProvider>))
  await fill('#convertible-as-of', '2026-10-20')
  await fill('#convertible-csv', csv)
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await settle()
}
function confirmButton() { return [...host.querySelectorAll('button')].find(button => button.textContent?.includes('确认替换研究清单')) }

it('预览不写入；修改 CSV 后必须重新预览才能确认替换', async () => {
  await start()
  expect(mocks.preview).toHaveBeenCalledWith({ csv_text: csv, as_of: '2026-10-20' }, expect.anything())
  expect(mocks.save).not.toHaveBeenCalled()
  expect(confirmButton()).toBeDefined()
  await fill('#convertible-csv', `${csv}\n100002,另一转债`)
  expect(confirmButton()).toBeUndefined()
  expect(mocks.save).not.toHaveBeenCalled()
})

it('行错误阻止保存，保留可定位的行号与原因', async () => {
  mocks.preview.mockResolvedValue({ ...validPreview, valid: false, errors: [{ row: 2, field: 'bond_price', message: '价格必须为正数' }] })
  await start()
  expect(host.textContent).toContain('第 2 行 · bond_price：价格必须为正数')
  expect(confirmButton()).toBeUndefined()
  expect(mocks.save).not.toHaveBeenCalled()
})

it('确认携带预览时版本，版本冲突后禁止直接重试覆盖', async () => {
  mocks.save.mockRejectedValue(new ApiError('版本已变化', 409))
  await start()
  await act(async () => confirmButton()!.click())
  await settle()
  expect(mocks.save).toHaveBeenCalledWith({ csv_text: csv, as_of: '2026-10-20', expected_revision: 'revision-1', confirmed: true }, expect.anything())
  expect(host.textContent).toContain('请点击“校验并预览”重新核对')
  expect(confirmButton()!.disabled).toBe(true)
  expect(mocks.saved).not.toHaveBeenCalled()
})
