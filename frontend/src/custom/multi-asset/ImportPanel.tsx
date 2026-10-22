import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, FileUp, Loader2, X } from 'lucide-react'
import { api, ApiError, type MultiAssetCategory, type MultiAssetImportInput, type MultiAssetImportPreview, type MultiAssetSnapshot } from '@/lib/api'
import { AssetTable, researchColumns } from './AssetTable'
import { BUTTON, INPUT, PRIMARY_BUTTON } from './model'

const MAX_BYTES = 2 * 1024 * 1024
export function ImportPanel({ category, snapshot, onClose, onSaved, onReload, onTemplate }: {
  category: MultiAssetCategory; snapshot: MultiAssetSnapshot; onClose: () => void
  onSaved: (data: MultiAssetSnapshot) => void | Promise<void>; onReload: () => Promise<MultiAssetSnapshot>
  onTemplate: () => void
}) {
  const [csv, setCsv] = useState('')
  const [error, setError] = useState('')
  const [reading, setReading] = useState(false)
  const [preview, setPreview] = useState<{ input: MultiAssetImportInput; result: MultiAssetImportPreview } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const previewMutation = useMutation({ mutationFn: api.previewMultiAssetImport, onSuccess: (result, input) => setPreview({ result, input }) })
  const saveMutation = useMutation({ mutationFn: api.importMultiAsset, onSuccess: onSaved })
  const busy = reading || previewMutation.isPending || saveMutation.isPending
  const conflict = [saveMutation.error, previewMutation.error].some(value => value instanceof ApiError && value.status === 409)
  function reset() { setPreview(null); setError(''); previewMutation.reset(); saveMutation.reset() }
  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = ''
    if (!file) return
    reset()
    if (file.size > MAX_BYTES) { setError('文件超过 2 MiB，请缩小文件后重试。'); return }
    setReading(true)
    try { setCsv(new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())) }
    catch { setError('请使用 UTF-8 编码的 CSV 文件。'); setCsv('') }
    finally { setReading(false) }
  }
  async function validate(reload = false) {
    reset()
    if (!csv.trim()) { setError('请选择 CSV 文件或粘贴带表头的内容。'); return }
    if (new TextEncoder().encode(csv).length > MAX_BYTES) { setError('CSV 内容超过 2 MiB。'); return }
    setReading(true)
    try {
      const current = reload ? await onReload() : snapshot
      await previewMutation.mutateAsync({ category: category.id, csv_text: csv, expected_revision: current.revision })
    } catch (reason) {
      // The mutation supplies structured API errors; reload failures need their own message.
      setError(reason instanceof Error ? reason.message : '校验失败，请重试。')
    } finally { setReading(false) }
  }
  function submit(event: FormEvent) { event.preventDefault(); void validate() }
  const rowWarnings = preview?.result.rows.flatMap(row => row.warnings.map(warning => `${row.code}：${warning}`)) ?? []
  return <section aria-label={`导入 ${category.label}`} className="overflow-hidden rounded-card border border-accent/30 bg-surface">
    <div className="flex items-start justify-between gap-4 border-b border-border p-4 sm:px-5"><div><h3 className="flex items-center gap-2 text-sm font-semibold"><FileUp className="h-4 w-4 text-accent" />导入 {category.label} 研究清单</h3><p className="mt-1 text-xs leading-relaxed text-muted">先预览，再确认替换本类别。其他类别与原有基金、可转债资料不受影响。</p></div><button type="button" aria-label="关闭导入" disabled={busy} onClick={onClose} className="rounded p-1.5 hover:bg-elevated disabled:opacity-40"><X className="h-4 w-4" /></button></div>
    <form className="space-y-4 p-4 sm:p-5" onSubmit={submit}>
      <div className="flex flex-wrap gap-2"><input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="选择多资产 CSV 文件" disabled={busy} onChange={event => void readFile(event)} className="sr-only" /><button type="button" onClick={() => fileRef.current?.click()} disabled={busy} className={BUTTON}>选择 CSV 文件</button><button type="button" onClick={onTemplate} className={BUTTON}>下载空白模板</button></div>
      <div><label htmlFor="multi-asset-csv" className="mb-2 block text-xs font-medium">CSV 内容 <span className="font-normal text-muted">· UTF-8 · 最大 2 MiB</span></label><textarea id="multi-asset-csv" value={csv} onChange={event => { reset(); setCsv(event.target.value) }} disabled={busy} placeholder="使用模板中的英文表头，或直接粘贴 CSV 内容" className={`${INPUT} h-40 w-full resize-y font-mono text-xs leading-relaxed`} spellCheck={false} /></div>
      <details className="rounded-btn border border-border p-3 text-xs"><summary className="cursor-pointer font-medium">字段与口径说明（{category.fields.length} 项）</summary><p className="mt-3 leading-relaxed text-secondary">必填：{category.fields.filter(field => field.required).map(field => `${field.label} (${field.key})`).join('、')}。日期填写 YYYY-MM-DD，百分比 2.5 表示 2.5%，未知数值留空。</p><dl className="mt-3 space-y-3">{category.fields.map(field => <div key={field.key}><dt className="text-secondary">{field.label} · <code className="text-accent">{field.key}</code>{field.required ? ' · 必填' : ''}</dt><dd className="mt-1 text-muted">{field.description || (field.type === 'number' ? '数字，未知时留空。' : field.type === 'date' ? '日期格式 YYYY-MM-DD。' : '文本，使用模板字段名。')}</dd></div>)}</dl></details>
      <button type="submit" disabled={busy || !csv.trim()} className={PRIMARY_BUTTON}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}校验并预览</button>
      {(error || previewMutation.isError) && !conflict && <p role="alert" className="text-xs text-danger">{error || previewMutation.error?.message}</p>}
    </form>
    {preview && <div className="border-t border-border"><div className="p-4 sm:px-5"><h4 className="text-sm font-semibold">导入预览 · {preview.result.row_count} 条</h4><p className="mt-1 text-xs text-muted">仅展示前 8 条；尚未保存。原清单 {snapshot.rows.length} 条将被本次完整清单替换。</p>{preview.result.warnings.length > 0 && <ul className="mt-3 list-inside list-disc space-y-1 text-xs text-warning">{preview.result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}</div><AssetTable rows={preview.result.rows.slice(0, 8)} columns={researchColumns(category)} caption="多资产导入预览" /><div className="space-y-3 p-4 sm:p-5"><p className="text-xs leading-relaxed text-secondary">清单外标的会从本类别移除。请先导出需要保留的旧清单；确认后仍标记为“用户导入 · 未核验”。</p><button type="button" disabled={busy || conflict} className={PRIMARY_BUTTON} onClick={() => { if (preview) saveMutation.mutate({ ...preview.input, confirmed: true }) }}>{saveMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}确认替换本类别清单</button></div></div>}
    {rowWarnings.length > 0 && <details open className="m-4 rounded-btn border border-warning/25 bg-warning/5 p-3 text-xs"><summary className="cursor-pointer font-medium text-warning">字段与计算提示 · {rowWarnings.length} 项</summary><ul className="mt-2 max-h-48 list-inside list-disc space-y-1 overflow-y-auto leading-relaxed text-secondary">{rowWarnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    {conflict ? <div role="alert" className="space-y-3 border-t border-warning/20 bg-warning/5 p-4 text-xs"><p>数据已被其他操作更新。请重新读取当前版本并检查预览，再确认替换。</p><button type="button" className={BUTTON} disabled={busy} onClick={() => void validate(true)}>重新读取并校验</button></div> : saveMutation.isError && <p role="alert" className="px-4 pb-4 text-xs text-danger">{saveMutation.error.message}</p>}
  </section>
}
