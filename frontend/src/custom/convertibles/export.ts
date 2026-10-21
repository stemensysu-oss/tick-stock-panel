import type { ConvertibleItem } from '@/lib/api'
import { COLUMNS, type ColumnId } from './columns'

/** Keep numbers numeric; protect textual spreadsheet formulas from imported names. */
export function csvCell(value: unknown): string {
  if (value == null) return ''
  let text = String(value)
  if (typeof value === 'string' && /^[\s]*[=+@\-]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}
export function createConvertibleCsv(items: ConvertibleItem[], columns: ColumnId[]): string {
  const chosen = COLUMNS.filter(column => columns.includes(column.id))
  return '\uFEFF' + [chosen.map(column => csvCell(column.id)).join(','), ...items.map(item => chosen.map(column => csvCell(item[column.id])).join(','))].join('\r\n') + '\r\n'
}
export function downloadText(text: string, filename: string, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
