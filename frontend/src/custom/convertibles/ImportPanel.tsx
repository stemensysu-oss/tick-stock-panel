import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Download, FileUp, Info, Loader2, X } from 'lucide-react'
import { api, ApiError, type ConvertibleDataset, type ConvertibleImportInput, type ConvertiblePreview } from '@/lib/api'
import { ConvertibleTable } from './ConvertibleTable'

const MAX_CSV_BYTES = 2 * 1024 * 1024
const CSV_HEADER = 'code,name,bond_price,stock_code,stock_name,stock_price,conversion_price,face_value,maturity_date,redemption_status\r\n'
const BUTTON = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border px-3 py-2 text-xs font-medium transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40'

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob(['\uFEFF', CSV_HEADER], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'convertibles-template.csv'
  link.click()
  URL.revokeObjectURL(url)
}

export function ImportPanel({ existingCount, onClose, onSaved }: { existingCount: number; onClose: () => void; onSaved: (dataset: ConvertibleDataset) => void | Promise<void> }) {
  const [csvText, setCsvText] = useState('')
  const [asOf, setAsOf] = useState('')
  const [fileName, setFileName] = useState('')
  const [error, setError] = useState('')
  const [reading, setReading] = useState(false)
  const [preview, setPreview] = useState<{ input: ConvertibleImportInput; result: ConvertiblePreview } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const previewMutation = useMutation({ mutationFn: api.previewConvertibles, onSuccess: (result, input) => setPreview({ result, input }) })
  const saveMutation = useMutation({ mutationFn: api.importConvertibles, onSuccess: onSaved })
  const busy = reading || previewMutation.isPending || saveMutation.isPending
  const resetPreview = () => { setPreview(null); setError(''); previewMutation.reset(); saveMutation.reset() }

  const readFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    resetPreview()
    if (file.size > MAX_CSV_BYTES) { setError('文件超过 2 MiB，请缩小至最多 2,000 条数据后重试。'); return }
    setReading(true)
    try {
      const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
      setCsvText(content)
      setFileName(file.name)
    } catch {
      setError('无法读取 UTF-8 文件。请从表格软件另存为“CSV UTF-8（逗号分隔）”后重试。')
    } finally { setReading(false) }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    resetPreview()
    if (!csvText.trim() || !asOf) { setError('请提供 CSV 内容及该批数据的实际日期。'); return }
    if (new TextEncoder().encode(csvText).length > MAX_CSV_BYTES) { setError('CSV 内容超过 2 MiB，请缩小后重试。'); return }
    previewMutation.mutate({ csv_text: csvText, as_of: asOf })
  }

  const confirm = () => {
    if (!preview?.result.valid || preview.result.errors.length || busy) return
    saveMutation.mutate({ ...preview.input, expected_revision: preview.result.base_revision, confirmed: true })
  }
  const conflict = saveMutation.error instanceof ApiError && saveMutation.error.status === 409

  return (
    <section aria-label="导入可转债" className="overflow-hidden rounded-card border border-accent/30 bg-surface">
      <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-4 sm:px-5"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><FileUp className="h-4 w-4 text-accent" />导入研究清单</h2><p className="mt-1 text-[11px] text-muted">先校验预览，再由你确认保存。支持 UTF-8 CSV，最多 2,000 条、2 MiB。</p></div><button type="button" aria-label="关闭导入" onClick={onClose} disabled={busy} className="rounded p-1.5 text-muted hover:bg-elevated disabled:opacity-40"><X className="h-4 w-4" /></button></div>
      <form onSubmit={submit} className="space-y-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div><label htmlFor="convertible-as-of" className="mb-2 block text-xs font-medium text-secondary">数据日期 <span className="text-muted">（必填）</span></label><input id="convertible-as-of" type="date" value={asOf} onChange={event => { resetPreview(); setAsOf(event.target.value) }} disabled={busy} required className="h-9 rounded-input border border-border bg-base px-3 text-sm outline-none focus:border-accent disabled:opacity-50" /></div>
          <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="选择可转债 CSV 文件" onChange={event => void readFile(event)} className="sr-only" disabled={busy} />
          <button type="button" onClick={() => fileRef.current?.click()} disabled={busy} className={BUTTON}><FileUp className="h-3.5 w-3.5" />选择 CSV</button>
          <button type="button" onClick={downloadTemplate} className={BUTTON}><Download className="h-3.5 w-3.5" />下载空白模板</button>
          {fileName && <span className="max-w-full break-all text-[11px] text-muted">{fileName}</span>}
        </div>
        <div><label htmlFor="convertible-csv" className="mb-2 block text-xs font-medium text-secondary">CSV 内容</label><textarea id="convertible-csv" value={csvText} onChange={event => { resetPreview(); setCsvText(event.target.value); setFileName('') }} disabled={busy} required spellCheck={false} placeholder="选择文件，或粘贴含表头的 CSV 内容" className="h-36 w-full resize-y rounded-input border border-border bg-base px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-accent disabled:opacity-50" /></div>
        <details className="rounded-btn border border-border bg-base/40 px-3 py-2 text-[11px] text-secondary"><summary className="cursor-pointer font-medium">字段与导入口径</summary><div className="mt-2 space-y-2 leading-relaxed"><p>必需：code（转债代码）、name（转债名称）。可选：bond_price（现价）、stock_code / stock_name（正股代码 / 名称）、stock_price（正股价）、conversion_price（转股价）、face_value（面值）、maturity_date（到期日期）、redemption_status（强赎状态）。也接受对应的常见中文表头。</p><p>代码须保留六位数字，可带 .SH / .SZ / .BJ；请在表格软件中将代码列设为文本。价格单位均为元；未知价格留空，不能用 0 代替。本版仅支持每张面值 100 元人民币的可转债，其他面值不接受导入；面值未填时按 100 元处理，预览会提示。日期使用 YYYY-MM-DD。</p><p>数据日期应是这批行情的实际日期。强赎状态按原文记录，未提供显示“未知”；不会自动判断条款是否触发。</p></div></details>
        {(error || previewMutation.isError) && <p role="alert" className="text-xs leading-relaxed text-danger">{error || previewMutation.error?.message}</p>}
        <button type="submit" disabled={busy || !asOf || !csvText.trim()} className={`${BUTTON} border-accent/30 bg-accent/10 text-accent hover:bg-accent/15`}>{previewMutation.isPending || reading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}{previewMutation.isPending ? '正在校验…' : '校验并预览'}</button>
      </form>

      {preview && <div className="border-t border-border">
        <div className="space-y-3 px-4 py-4 sm:px-5"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">导入预览</h3><span className="text-xs text-muted">{preview.result.as_of} · 共 {preview.result.total_rows} 条</span></div>
          {preview.result.errors.length > 0 && <div role="alert" className="rounded-btn border border-danger/25 bg-danger/5 p-3 text-xs"><p className="font-medium text-danger">发现 {preview.result.errors.length} 项错误，整批数据尚未保存</p><ul className="mt-2 max-h-48 list-inside list-disc space-y-1 overflow-y-auto text-secondary">{preview.result.errors.map((item, index) => <li key={index}>第 {item.row} 行{item.field ? ` · ${item.field}` : ''}：{item.message}</li>)}</ul></div>}
          {preview.result.warnings.length > 0 && <div className="rounded-btn border border-warning/25 bg-warning/5 p-3 text-xs text-secondary"><p className="mb-1 font-medium text-warning">请核对以下提示</p><ul className="max-h-40 list-inside list-disc space-y-1 overflow-y-auto">{preview.result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
        </div>
        {preview.result.items.length > 0 && <><ConvertibleTable items={preview.result.items.slice(0, 8)} caption="可转债导入预览" /><p className="px-4 pt-2 text-[11px] text-muted sm:px-5">预览展示前 {Math.min(8, preview.result.items.length)} 条；确认后保存通过校验的完整清单。</p></>}
        {preview.result.valid && <div className="space-y-3 p-4 sm:p-5"><p className="flex items-start gap-2 text-xs leading-relaxed text-secondary"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />{existingCount > 0 ? `确认后将用这 ${preview.result.items.length} 条数据替换当前 ${existingCount} 条研究清单。原 CSV 请自行保留。` : `确认后保存这 ${preview.result.items.length} 条数据，后续可以重新导入更新。`}</p><button type="button" onClick={confirm} disabled={busy || conflict} className={`${BUTTON} border-accent/30 bg-accent text-white hover:bg-accent/90`}>{saveMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{saveMutation.isPending ? '正在保存…' : existingCount > 0 ? '确认替换研究清单' : '确认保存研究清单'}</button></div>}
      </div>}
      {saveMutation.isError && <p role="alert" className="px-4 pb-4 text-xs leading-relaxed text-danger sm:px-5">{conflict ? '研究清单已被其他操作更新。请点击“校验并预览”重新核对，再确认保存。' : saveMutation.error.message}</p>}
    </section>
  )
}
