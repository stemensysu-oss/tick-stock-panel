// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { RestorePanel } from './RestorePanel'

const mocks = vi.hoisted(() => ({ preview: vi.fn(), restore: vi.fn(), saved: vi.fn() }))
vi.mock('@/lib/api', () => ({
  ApiError: class extends Error { constructor(message: string, readonly status: number) { super(message) } },
  api: { previewConvertibleRestore: mocks.preview, restoreConvertibles: mocks.restore },
}))
let host: HTMLDivElement
let root: Root
let client: QueryClient
const snapshot = { schema_version: 1, revision: 'backup-revision', as_of: '2026-10-20', updated_at: null, source: '用户导入', items: [] }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.resetAllMocks()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  mocks.preview.mockResolvedValue({ valid: true, items: [], total_rows: 1, errors: [], warnings: [], as_of: '2026-10-20', base_revision: 'live-revision' })
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove() })
async function settle() { for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
async function render() { await act(async () => root.render(<QueryClientProvider client={client}><RestorePanel existingCount={3} onClose={() => {}} onSaved={mocks.saved} /></QueryClientProvider>)) }
async function file(content: unknown) {
  const data = new TextEncoder().encode(JSON.stringify(content))
  const element = host.querySelector<HTMLInputElement>('input[type="file"]')!
  Object.defineProperty(element, 'files', { value: [{ name: 'research.json', size: data.length, arrayBuffer: async () => data.buffer }], configurable: true })
  await act(async () => element.dispatchEvent(new Event('change', { bubbles: true }))); await settle()
}
async function click(text: string) { const button = [...host.querySelectorAll('button')].find(value => value.textContent === text)!; await act(async () => button.click()); await settle() }
const confirm = () => [...host.querySelectorAll('button')].find(value => value.textContent === '确认恢复并替换研究资料')
it('恢复前强制预览，携带当前revision而不是备份revision，冲突保护已有研究', async () => {
  await render(); await file(snapshot)
  expect(confirm()).toBeUndefined()
  await click('校验备份并预览')
  expect(mocks.restore).not.toHaveBeenCalled()
  mocks.restore.mockRejectedValue(new ApiError('版本冲突', 409))
  await click('确认恢复并替换研究资料')
  expect(mocks.restore).toHaveBeenCalledWith({ snapshot, expected_revision: 'live-revision', confirmed: true }, expect.anything())
  expect(confirm()!.disabled).toBe(true)
  expect(host.textContent).toContain('当前资料没有被覆盖')
  expect(mocks.saved).not.toHaveBeenCalled()
})
it('换备份后旧预览立即失效，未来schema版本不进入请求', async () => {
  await render(); await file(snapshot); await click('校验备份并预览')
  expect(confirm()).toBeDefined()
  await file({ ...snapshot, schema_version: 2 })
  expect(confirm()).toBeUndefined()
  expect(host.textContent).toContain('版本 1 研究备份')
  expect(mocks.preview).toHaveBeenCalledTimes(1)
})
