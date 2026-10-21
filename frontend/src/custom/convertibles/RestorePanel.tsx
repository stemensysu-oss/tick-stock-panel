import { useRef, useState, type ChangeEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, FileUp, Loader2, X } from 'lucide-react'
import { api, ApiError, type ConvertibleDataset, type ConvertiblePreview } from '@/lib/api'
import { BUTTON } from './columns'
import { ConvertibleTable } from './ConvertibleTable'

const MAX_BACKUP_BYTES = 32 * 1024 * 1024
export function RestorePanel({ existingCount, onClose, onSaved }: { existingCount: number; onClose: () => void; onSaved: (dataset: ConvertibleDataset) => void | Promise<void> }) {
  const input = useRef<HTMLInputElement>(null)
  const [snapshot, setSnapshot] = useState<ConvertibleDataset | null>(null)
  const [filename, setFilename] = useState('')
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<ConvertiblePreview | null>(null)
  const inspect = useMutation({ mutationFn: api.previewConvertibleRestore, onSuccess: setPreview })
  const restore = useMutation({ mutationFn: api.restoreConvertibles, onSuccess: onSaved })
  const busy = reading || inspect.isPending || restore.isPending
  const conflict = restore.error instanceof ApiError && restore.error.status === 409
  const read = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file) return
    setSnapshot(null); setPreview(null); setError(''); setFilename(file.name); inspect.reset(); restore.reset()
    if (file.size > MAX_BACKUP_BYTES) { setError('研究备份不能超过 32 MiB。'); return }
    setReading(true)
    try {
      const parsed: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()).replace(/^\uFEFF/, ''))
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !('schema_version' in parsed) || parsed.schema_version !== 1 || !('items' in parsed) || !Array.isArray(parsed.items)) throw new Error('请选择本工作台导出的版本 1 研究备份 JSON。')
      setSnapshot(parsed as ConvertibleDataset)
    } catch (value) { setError(value instanceof Error && value.message.startsWith('请选择') ? value.message : '备份不是有效的 UTF-8 JSON 文件，请重新选择。') }
    finally { setReading(false) }
  }
  return <section aria-label="恢复可转债研究备份" className="overflow-hidden rounded-card border border-accent/30 bg-surface">
    <div className="flex items-start justify-between gap-3 border-b border-border p-4"><div><h2 className="text-sm font-semibold">恢复研究备份</h2><p className="mt-1 text-[11px] leading-relaxed text-muted">恢复清单、现金流、条款观察和公告。先预览核对，确认后整份替换；自选与显示列仍为本机设置。</p></div><button type="button" aria-label="关闭备份恢复" onClick={onClose} disabled={busy} className="rounded p-1.5 text-muted hover:bg-elevated disabled:opacity-40"><X className="h-4 w-4" /></button></div>
    <div className="space-y-3 p-4"><input type="file" ref={input} accept=".json,application/json" aria-label="选择研究备份 JSON" className="sr-only" disabled={busy} onChange={event => void read(event)} /><div className="flex flex-wrap items-center gap-3"><button type="button" onClick={() => input.current?.click()} disabled={busy} className={BUTTON}><FileUp className="h-3.5 w-3.5" />选择研究备份</button><button type="button" disabled={!snapshot || busy} onClick={() => { if (snapshot) { setPreview(null); restore.reset(); inspect.mutate({ snapshot }) } }} className={`${BUTTON} border-accent/30 text-accent`}>{inspect.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}校验备份并预览</button><span className="max-w-full break-all text-[11px] text-muted">{reading ? '正在读取…' : filename || '最多 32 MiB'}</span></div>{(error || inspect.isError) && <p role="alert" className="text-xs text-danger">{error || inspect.error?.message}</p>}</div>
    {preview && <div className="border-t border-border"><div className="space-y-2 p-4"><p className="text-sm font-medium">备份预览 · {preview.total_rows} 只 · {preview.as_of}</p>{preview.errors.length > 0 && <ul role="alert" className="space-y-1 text-xs text-danger">{preview.errors.slice(0, 30).map((issue, i) => <li key={i}>第 {issue.row} 项{issue.field ? ` · ${issue.field}` : ''}：{issue.message}</li>)}</ul>}{preview.warnings.length > 0 && <ul className="space-y-1 text-[11px] text-warning">{preview.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}</div>{preview.items.length > 0 && <ConvertibleTable items={preview.items.slice(0, 5)} caption="研究备份恢复预览，仅展示前五条" />}{preview.valid && <div className="space-y-3 p-4"><p className="text-xs leading-relaxed text-secondary">确认后用备份中的 {preview.items.length} 只转债及全部研究资料替换当前 {existingCount} 只清单。请先保存需要保留的当前备份；这一步不会合并两份现金流或公告记录。</p><button type="button" disabled={busy || conflict} onClick={() => { if (snapshot) restore.mutate({ snapshot, expected_revision: preview.base_revision, confirmed: true }) }} className={`${BUTTON} border-accent/30 bg-accent text-white hover:bg-accent/90`}>{restore.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}确认恢复并替换研究资料</button></div>}</div>}
    {restore.isError && <p role="alert" className="p-4 text-xs text-danger">{conflict ? '清单已被其他操作更新。请重新校验备份并核对后再恢复，当前资料没有被覆盖。' : restore.error.message}</p>}
  </section>
}
