// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type ContentTypography, type Preferences } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { getContentTypography } from '@/lib/contentTypography'
import { ContentTypographySettings } from './ContentTypographySettings'

let root: Root
let container: HTMLDivElement
let qc: QueryClient
const defaults = { content_font_size: 18, content_font_family: 'default' } as const

async function render(values: ContentTypography = defaults) {
  qc.setQueryData(QK.preferences, { ...values, nav_hidden: ['/data'] })
  await act(async () => {
    root.render(<QueryClientProvider client={qc}><ContentTypographySettings /></QueryClientProvider>)
  })
}

async function change(selector: string, value: string) {
  const select = container.querySelector<HTMLSelectElement>(selector)!
  await act(async () => {
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  localStorage.clear()
  document.documentElement.style.cssText = ''
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

it('hydrates saved preferences, previews a change and updates the shared cache without losing other preferences', async () => {
  const save = vi.spyOn(api, 'updateContentTypography').mockImplementation(async values => values)
  await render({ content_font_size: 20, content_font_family: 'pingfang' })
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.value).toBe('20')
  expect(container.querySelector<HTMLSelectElement>('#content-font-family')!.value).toBe('pingfang')
  await change('#content-font-family', 'microsoft-yahei')
  expect(save).toHaveBeenCalledWith({ content_font_size: 20, content_font_family: 'microsoft-yahei' })
  expect(document.documentElement.style.getPropertyValue('--content-font-family')).toContain('Microsoft YaHei')
  expect(qc.getQueryData<Preferences>(QK.preferences)?.nav_hidden).toEqual(['/data'])
  expect(qc.getQueryData<Preferences>(QK.preferences)?.content_font_family).toBe('microsoft-yahei')
  expect(container.textContent).toContain('已保存')
})

it('disables concurrent changes while saving and restores the last saved appearance on failure', async () => {
  let reject!: (error: Error) => void
  vi.spyOn(api, 'updateContentTypography').mockImplementation(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
  await render()
  await change('#content-font-size', '22')
  expect(getContentTypography().content_font_size).toBe(22)
  expect(container.querySelector<HTMLSelectElement>('#content-font-family')!.disabled).toBe(true)
  await act(async () => reject(new Error('network unavailable')))
  expect(getContentTypography()).toEqual(defaults)
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.value).toBe('18')
  expect(container.textContent).toContain('保存失败，已恢复原设置')
  expect(container.querySelector<HTMLSelectElement>('#content-font-family')!.disabled).toBe(false)
})

it('keeps the newly saved typography when another setting starts an old preferences read during the PUT', async () => {
  let finishSave!: (values: ContentTypography) => void
  let finishOldRead!: (values: Preferences) => void
  vi.spyOn(api, 'updateContentTypography').mockImplementation(() => new Promise(resolve => { finishSave = resolve }))
  const read = vi.spyOn(api, 'preferences').mockImplementation(() => new Promise(resolve => { finishOldRead = resolve }))
  await render()
  await change('#content-font-size', '22')
  let invalidation!: Promise<void>
  await act(async () => {
    // A separate settings mutation can start this after the font save's initial cancellation.
    invalidation = qc.invalidateQueries({ queryKey: QK.preferences })
  })
  expect(read).toHaveBeenCalledTimes(1)
  const saved = { content_font_size: 22, content_font_family: 'default' } as const
  await act(async () => finishSave(saved))
  expect(qc.getQueryData<Preferences>(QK.preferences)?.content_font_size).toBe(22)
  await act(async () => {
    finishOldRead({ ...defaults, nav_hidden: ['/data'] } as Preferences)
    await invalidation
  })
  expect(qc.getQueryData<Preferences>(QK.preferences)?.content_font_size).toBe(22)
  expect(getContentTypography()).toEqual(saved)
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.value).toBe('22')
})

it('restores size and family defaults together and keeps boundaries usable', async () => {
  const save = vi.spyOn(api, 'updateContentTypography').mockImplementation(async values => values)
  await render({ content_font_size: 22, content_font_family: 'source-han' })
  expect(container.querySelector<HTMLButtonElement>('[aria-label="放大内容字体"]')!.disabled).toBe(true)
  const reset = Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('恢复字体默认值'))!
  await act(async () => reset.click())
  expect(save).toHaveBeenCalledWith(defaults)
  expect(getContentTypography()).toEqual(defaults)
  expect(reset.disabled).toBe(true)
})

it('keeps the preview reactive when localStorage writes are blocked', async () => {
  vi.spyOn(api, 'updateContentTypography').mockImplementation(async values => values)
  await render()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('disabled') })
  await change('#content-font-size', '21')
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.value).toBe('21')
  expect(Number(document.documentElement.style.getPropertyValue('--content-font-scale'))).toBeCloseTo(21 / 18)
  expect(qc.getQueryData<Preferences>(QK.preferences)?.content_font_size).toBe(21)
})

it('disables editing until preferences load and offers a working retry after an error', async () => {
  const read = vi.spyOn(api, 'preferences').mockRejectedValue(new Error('offline'))
  await act(async () => {
    root.render(<QueryClientProvider client={qc}><ContentTypographySettings /></QueryClientProvider>)
    await new Promise(resolve => setTimeout(resolve, 20))
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.disabled).toBe(true)
  expect(container.textContent).toContain('读取设置失败')
  read.mockResolvedValue({ ...defaults, content_font_size: 19 } as Preferences)
  const retry = Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('重试加载'))!
  await act(async () => {
    retry.click()
    await new Promise(resolve => setTimeout(resolve, 20))
  })
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.disabled).toBe(false)
  expect(container.querySelector<HTMLSelectElement>('#content-font-size')!.value).toBe('19')
})
