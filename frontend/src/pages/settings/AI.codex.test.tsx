// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SettingsAIPanel } from './AI'
import { api } from '@/lib/api'

const state = vi.hoisted(() => ({ data: {} as Record<string, unknown> }))
vi.mock('@/lib/useSharedQueries', () => ({ useSettings: () => ({ data: state.data }) }))
vi.mock('@/lib/sponsor-discount', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/sponsor-discount')>(),
  useSponsorModelItems: () => [],
}))

let root: Root
let container: HTMLDivElement
let qc: QueryClient
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  state.data = { ai_provider: 'codex_cli', ai_configured: true, ai_codex_model: '', ai_codex_reasoning_effort: '' }
  qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  qc.clear()
  container.remove()
  vi.restoreAllMocks()
})
async function render() {
  await act(async () => root.render(<QueryClientProvider client={qc}><SettingsAIPanel /></QueryClientProvider>))
}
it('offers GPT-6 and saves its exact model and effort without changing the command', async () => {
  const save = vi.spyOn(api, 'saveAiSettings').mockResolvedValue({ ok: true })
  await render()
  const select = [...container.querySelectorAll('select')].find(el => [...el.options].some(o => o.value === 'gpt-6-sol:high'))!
  expect(select.value).toBe('')
  await act(async () => { select.value = 'gpt-6-sol:high'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  const button = [...container.querySelectorAll('button')].find(el => el.textContent?.includes('保存配置'))!
  await act(async () => button.click())
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ provider: 'codex_cli', model: 'gpt-6-sol', codex_reasoning_effort: 'high', codex_command: 'codex' }))
})
it('preserves the saved older model until the user explicitly selects follow-default', async () => {
  state.data.ai_codex_model = 'gpt-5.6-sol'
  state.data.ai_codex_reasoning_effort = 'xhigh'
  const save = vi.spyOn(api, 'saveAiSettings').mockResolvedValue({ ok: true })
  await render()
  const select = [...container.querySelectorAll('select')].find(el => [...el.options].some(o => o.value === 'gpt-6-sol:high'))!
  expect(select.value).toBe('gpt-5.6-sol:xhigh')
  await act(async () => { select.value = ''; select.dispatchEvent(new Event('change', { bubbles: true })) })
  const button = [...container.querySelectorAll('button')].find(el => el.textContent?.includes('保存配置'))!
  await act(async () => button.click())
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ model: '', codex_reasoning_effort: '' }))
})
