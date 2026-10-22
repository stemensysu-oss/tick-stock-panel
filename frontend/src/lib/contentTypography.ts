import { useEffect, useState } from 'react'
import type { ContentTypography } from './api'

export const CONTENT_TYPOGRAPHY_KEY = 'tf-content-typography'
const EVENT = 'tf-content-typography-change'
export const CONTENT_FONT_MIN = 14
export const CONTENT_FONT_MAX = 22
export const CONTENT_TYPOGRAPHY_DEFAULT: ContentTypography = {
  content_font_size: 18, content_font_family: 'default',
}

const SYSTEM_FONT = 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
export const CONTENT_FONT_OPTIONS = [
  { value: 'default', label: '原有字体（默认）', css: 'Inter, "HarmonyOS Sans SC", "PingFang SC", system-ui, sans-serif' },
  { value: 'system', label: '系统字体', css: SYSTEM_FONT },
  { value: 'microsoft-yahei', label: '微软雅黑优先', css: `"Microsoft YaHei", "Microsoft YaHei UI", ${SYSTEM_FONT}` },
  { value: 'pingfang', label: '苹方优先', css: `"PingFang SC", ${SYSTEM_FONT}` },
  { value: 'source-han', label: '思源黑体优先', css: `"Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", ${SYSTEM_FONT}` },
] as const

export function normalizeContentTypography(raw: unknown): ContentTypography {
  const record = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  const size = typeof record.content_font_size === 'number' && Number.isFinite(record.content_font_size)
    ? Math.round(record.content_font_size) : 18
  const family = CONTENT_FONT_OPTIONS.find(option => option.value === record.content_font_family)?.value ?? 'default'
  return { content_font_size: Math.min(CONTENT_FONT_MAX, Math.max(CONTENT_FONT_MIN, size)), content_font_family: family }
}

/** 浏览器副本仅用于首屏; Layout 在偏好 API 返回后用持久化配置覆盖。 */
export function getContentTypography(): ContentTypography {
  try { return normalizeContentTypography(JSON.parse(localStorage.getItem(CONTENT_TYPOGRAPHY_KEY) || 'null')) }
  catch { return { ...CONTENT_TYPOGRAPHY_DEFAULT } }
}

export function applyContentTypography(raw: unknown): ContentTypography {
  const values = normalizeContentTypography(raw)
  const font = CONTENT_FONT_OPTIONS.find(option => option.value === values.content_font_family)!
  document.documentElement.style.setProperty('--content-font-scale', String(values.content_font_size / 18))
  document.documentElement.style.setProperty('--content-font-family', font.css)
  // 调整正文可能改变图表容器大小; 仅重排画布, 保留图内固定字号与坐标命中。
  window.dispatchEvent(new Event('resize'))
  return values
}

export function setContentTypography(raw: unknown): ContentTypography {
  const values = applyContentTypography(raw)
  try { localStorage.setItem(CONTENT_TYPOGRAPHY_KEY, JSON.stringify(values)) } catch { /* API 仍持久保存。 */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: values }))
  return values
}

export function useContentTypography(): ContentTypography {
  const [values, setValues] = useState(getContentTypography)
  useEffect(() => {
    const update = (event: Event) => setValues(normalizeContentTypography((event as CustomEvent).detail))
    const storageChange = (event: StorageEvent) => {
      if (event.key === CONTENT_TYPOGRAPHY_KEY || event.key === null) {
        applyContentTypography(getContentTypography())
        setValues(getContentTypography())
      }
    }
    window.addEventListener(EVENT, update)
    window.addEventListener('storage', storageChange)
    return () => {
      window.removeEventListener(EVENT, update)
      window.removeEventListener('storage', storageChange)
    }
  }, [])
  return values
}

/** 根布局及联调宿主共用同一入口, 后端配置权威且不因其他偏好刷新而反复重排。 */
export function useContentTypographySync(preferences: Partial<ContentTypography> | undefined) {
  const size = preferences?.content_font_size
  const family = preferences?.content_font_family
  const ready = preferences !== undefined
  useEffect(() => {
    if (ready) setContentTypography({ content_font_size: size, content_font_family: family })
  }, [ready, size, family])
}
