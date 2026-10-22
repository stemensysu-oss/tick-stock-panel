import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import { api, type ContentTypography, type Preferences } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { usePreferences } from '@/lib/useSharedQueries'
import {
  CONTENT_FONT_MIN, CONTENT_FONT_MAX, CONTENT_FONT_OPTIONS, CONTENT_TYPOGRAPHY_DEFAULT,
  setContentTypography, useContentTypography, useContentTypographySync,
} from '@/lib/contentTypography'

export function ContentTypographySettings() {
  const qc = useQueryClient()
  const { data: preferences, isError, isFetching, refetch } = usePreferences()
  const values = useContentTypography()
  useContentTypographySync(preferences)
  const savingRef = useRef(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const disabled = saving || preferences === undefined
  const isDefault = values.content_font_size === 18 && values.content_font_family === 'default'

  async function save(next: ContentTypography) {
    if (savingRef.current || preferences === undefined) return
    savingRef.current = true
    setSaving(true)
    setMessage('')
    setFailed(false)
    await qc.cancelQueries({ queryKey: QK.preferences })
    const previous = values
    setContentTypography(next)
    try {
      const saved = await api.updateContentTypography(next)
      // Other settings may invalidate this shared query while the PUT is running.
      // Cancel those older reads before publishing the authoritative saved values.
      await qc.cancelQueries({ queryKey: QK.preferences })
      setContentTypography(saved)
      qc.setQueryData<Preferences>(QK.preferences, current => current ? { ...current, ...saved } : current)
      setMessage('已保存，重新打开仍生效')
    } catch {
      setContentTypography(previous)
      setFailed(true)
      setMessage('保存失败，已恢复原设置，请重试')
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return <div className="border-b border-border pb-4 mb-3 space-y-4" aria-label="内容字体设置">
    <div>
      <h4 className="text-sm font-medium text-foreground">内容字体</h4>
      <p className="text-xs text-muted mt-1 leading-relaxed">调整页面正文、列表和弹窗，立即预览并保存。侧栏菜单保持原样；行情数字保留等宽字体，图表内坐标及图例保持原字号。</p>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <label htmlFor="content-font-size" className="text-sm text-foreground">字号基准</label>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" aria-label="缩小内容字体" disabled={disabled || values.content_font_size <= CONTENT_FONT_MIN}
          onClick={() => void save({ ...values, content_font_size: values.content_font_size - 1 })}
          className="inline-flex items-center justify-center h-8 w-8 rounded-btn bg-elevated text-secondary disabled:opacity-40">
          <Minus className="h-3.5 w-3.5" />
        </button>
        <select id="content-font-size" value={values.content_font_size} disabled={disabled}
          onChange={event => void save({ ...values, content_font_size: Number(event.target.value) })}
          className="min-h-9 px-2 rounded-btn border border-border bg-base text-sm text-foreground disabled:opacity-50">
          {Array.from({ length: CONTENT_FONT_MAX - CONTENT_FONT_MIN + 1 }, (_, index) => CONTENT_FONT_MIN + index).map(size =>
            <option key={size} value={size}>{size}px{size === 18 ? '（默认）' : ''}</option>)}
        </select>
        <button type="button" aria-label="放大内容字体" disabled={disabled || values.content_font_size >= CONTENT_FONT_MAX}
          onClick={() => void save({ ...values, content_font_size: values.content_font_size + 1 })}
          className="inline-flex items-center justify-center h-8 w-8 rounded-btn bg-elevated text-secondary disabled:opacity-40">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <label htmlFor="content-font-family" className="text-sm text-foreground">字体选择</label>
      <select id="content-font-family" value={values.content_font_family} disabled={disabled}
        onChange={event => void save({ ...values, content_font_family: event.target.value as ContentTypography['content_font_family'] })}
        className="min-h-9 max-w-full px-2 rounded-btn border border-border bg-base text-sm text-foreground disabled:opacity-50">
        {CONTENT_FONT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </div>
    <p className="text-xs text-muted leading-relaxed">字号按比例保留标题与辅助文字的层次。字体使用本机已安装的字库，缺少所选字体时自动使用系统后备字体，不在线下载。</p>
    <div className="rounded-btn border border-border bg-base p-3 space-y-1" aria-label="内容字体预览">
      <div className="text-sm text-foreground">腾讯控股 · 基金研究 · 可转债条款</div>
      <div className="text-xs text-secondary">正文预览：申购限额、收益口径与数据来源</div>
      <div className="text-sm num text-foreground">00700.HK　123.45　+1.23%</div>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <button type="button" disabled={disabled || isDefault} onClick={() => void save(CONTENT_TYPOGRAPHY_DEFAULT)}
        className="inline-flex items-center gap-1.5 px-2.5 py-2 rounded-btn text-xs bg-elevated text-secondary hover:text-foreground disabled:opacity-40">
        <RotateCcw className="h-3.5 w-3.5" />恢复字体默认值
      </button>
      <span role="status" aria-live="polite" className={`text-xs ${failed || isError ? 'text-warning' : 'text-muted'}`}>
        {saving ? '保存中…' : !preferences ? (isError ? '读取设置失败，请重试' : '读取设置中…') : message}
      </span>
      {isError && !preferences && <button type="button" disabled={isFetching} onClick={() => void refetch()}
        className="px-2.5 py-2 rounded-btn text-xs bg-elevated text-secondary disabled:opacity-40">重试加载字体设置</button>}
    </div>
  </div>
}
