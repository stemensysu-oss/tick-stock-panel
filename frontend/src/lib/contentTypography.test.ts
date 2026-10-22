// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import {
  applyContentTypography, getContentTypography, setContentTypography,
  CONTENT_TYPOGRAPHY_DEFAULT, CONTENT_TYPOGRAPHY_KEY, CONTENT_FONT_OPTIONS,
} from './contentTypography'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.cssText = ''
  document.body.innerHTML = '<aside id="nav" style="font-size:14px;font-family:Arial">菜单</aside><main class="content-typography">正文</main>'
})

it('keeps the current content appearance when no stored preference exists', () => {
  expect(getContentTypography()).toEqual(CONTENT_TYPOGRAPHY_DEFAULT)
  applyContentTypography(getContentTypography())
  expect(document.documentElement.style.getPropertyValue('--content-font-scale')).toBe('1')
  expect(document.getElementById('nav')!.style.fontSize).toBe('14px')
  expect(document.getElementById('nav')!.style.fontFamily).toBe('Arial')
})

it('persists selected content size and family and supports restoring defaults', () => {
  setContentTypography({ content_font_size: 22, content_font_family: 'microsoft-yahei' })
  expect(getContentTypography()).toEqual({ content_font_size: 22, content_font_family: 'microsoft-yahei' })
  expect(document.documentElement.style.getPropertyValue('--content-font-family')).toContain('Microsoft YaHei')
  document.documentElement.style.cssText = ''
  applyContentTypography(getContentTypography())
  expect(Number(document.documentElement.style.getPropertyValue('--content-font-scale'))).toBeCloseTo(22 / 18)
  setContentTypography(CONTENT_TYPOGRAPHY_DEFAULT)
  expect(getContentTypography()).toEqual(CONTENT_TYPOGRAPHY_DEFAULT)
  expect(document.documentElement.style.getPropertyValue('--content-font-scale')).toBe('1')
})

it('clamps stored sizes and only accepts allowlisted font families', () => {
  localStorage.setItem(CONTENT_TYPOGRAPHY_KEY, JSON.stringify({
    content_font_size: 500, content_font_family: 'url(https://invalid/font)',
  }))
  expect(getContentTypography()).toEqual({ content_font_size: 22, content_font_family: 'default' })
  expect(applyContentTypography({ content_font_size: -1, content_font_family: 'source-han' }).content_font_size).toBe(14)
  for (const raw of ['null', '[]', 'true', '"22"', '{bad']) {
    localStorage.setItem(CONTENT_TYPOGRAPHY_KEY, raw)
    expect(getContentTypography()).toEqual(CONTENT_TYPOGRAPHY_DEFAULT)
  }
})

it('applies even if browser storage is unavailable and never writes arbitrary CSS', () => {
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('disabled') })
  expect(() => setContentTypography({ content_font_size: 20, content_font_family: 'system' })).not.toThrow()
  expect(document.documentElement.style.getPropertyValue('--content-font-family')).toContain('system-ui')
  expect(CONTENT_FONT_OPTIONS.every(option => !option.css.includes('url('))).toBe(true)
  spy.mockRestore()
})
