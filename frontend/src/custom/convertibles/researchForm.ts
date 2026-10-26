import type { ConvertibleClause, ConvertibleEvent, ConvertibleResearch } from '@/lib/api'

export interface CashFlowDraft { date: string; amount: string }
export interface ClauseDraft {
  window_days: string; required_days: string; trigger_ratio_pct: string
  consecutive: boolean; start_date: string; end_date: string; paused_until: string; observations_complete: boolean
}
export interface ResearchDraft {
  calculation_settings?: ConvertibleResearch['calculation_settings']
  personal_rating?: string | null
  parameter_note?: string | null
  fund_holding_report_date?: string | null
  cash_flows: CashFlowDraft[]
  put_cash_flows: CashFlowDraft[]
  cash_flows_complete: boolean
  put_cash_flows_complete: boolean
  price_basis: '' | 'full' | 'clean'
  accrued_interest: string
  discount_rate_pct: string
  risk_free_rate_pct: string
  dividend_yield_pct: string
  call_clause: ClauseDraft | null
  put_clause: ClauseDraft | null
  observations: string
  observations_as_of: string | null
  events: ConvertibleEvent[]
}
export function blankClause(): ClauseDraft {
  return { window_days: '', required_days: '', trigger_ratio_pct: '', consecutive: false, start_date: '', end_date: '', paused_until: '', observations_complete: false }
}
const text = (value: number | null | undefined) => value == null ? '' : String(value)
function clauseDraft(clause: ConvertibleClause | null | undefined): ClauseDraft | null {
  return clause ? { ...clause, window_days: String(clause.window_days), required_days: String(clause.required_days), trigger_ratio_pct: String(clause.trigger_ratio_pct), start_date: clause.start_date ?? '', end_date: clause.end_date ?? '', paused_until: clause.paused_until ?? '' } : null
}
export function createResearchDraft(research?: ConvertibleResearch | null): ResearchDraft {
  return {
    calculation_settings: research?.calculation_settings,
    personal_rating: research?.personal_rating,
    parameter_note: research?.parameter_note,
    fund_holding_report_date: research?.fund_holding_report_date,
    cash_flows: (research?.cash_flows ?? []).map(flow => ({ date: flow.date, amount: String(flow.amount) })),
    put_cash_flows: (research?.put_cash_flows ?? []).map(flow => ({ date: flow.date, amount: String(flow.amount) })),
    cash_flows_complete: research?.cash_flows_complete ?? false,
    put_cash_flows_complete: research?.put_cash_flows_complete ?? false,
    price_basis: research?.price_basis ?? '', accrued_interest: text(research?.accrued_interest),
    discount_rate_pct: text(research?.discount_rate_pct), risk_free_rate_pct: text(research?.risk_free_rate_pct), dividend_yield_pct: text(research?.dividend_yield_pct),
    call_clause: clauseDraft(research?.call_clause), put_clause: clauseDraft(research?.put_clause),
    observations_as_of: research?.observations_as_of ?? null,
    observations: (research?.observations ?? []).map(row => `${row.date},${row.stock_close},${row.conversion_price}`).join('\n'),
    events: (research?.events ?? []).map(event => ({ ...event })),
  }
}
function dateValue(value: string, label: string): string {
  const date = new Date(`${value}T00:00:00Z`)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) throw new Error(`${label}须为有效的 YYYY-MM-DD 日期`)
  return value
}
function optionalNumber(value: string, label: string): number | null {
  if (!value.trim()) return null
  const number = Number(value)
  if (!Number.isFinite(number)) throw new Error(`${label}须为有限数字`)
  return number
}
function positive(value: string, label: string): number {
  const number = optionalNumber(value, label)
  if (number == null || number <= 0) throw new Error(`${label}须为正数`)
  return number
}
function cashFlows(rows: CashFlowDraft[], label: string) {
  const dates = new Set<string>()
  return rows.map((row, index) => {
    const date = dateValue(row.date, `${label}第 ${index + 1} 行日期`)
    if (dates.has(date)) throw new Error(`${label}同一天的款项请先合并为一行，避免重复计算末息`)
    dates.add(date)
    return { date, amount: positive(row.amount, `${label}第 ${index + 1} 行金额`) }
  })
}
function clauseValue(clause: ClauseDraft | null, label: string): ConvertibleClause | null {
  if (!clause) return null
  const window = positive(clause.window_days, `${label}观察窗口`)
  const required = positive(clause.required_days, `${label}所需天数`)
  if (!Number.isInteger(window) || !Number.isInteger(required) || window > 260 || required > window) throw new Error(`${label}窗口与天数须为 1–260 的整数，所需天数不能超过窗口`)
  const start = clause.start_date ? dateValue(clause.start_date, `${label}适用起日`) : null
  const end = clause.end_date ? dateValue(clause.end_date, `${label}适用止日`) : null
  if (start && end && end < start) throw new Error(`${label}适用止日不能早于起日`)
  return { ...clause, window_days: window, required_days: required, trigger_ratio_pct: positive(clause.trigger_ratio_pct, `${label}触发比例`), start_date: start, end_date: end, paused_until: clause.paused_until ? dateValue(clause.paused_until, `${label}暂停截止日`) : null }
}
export function parseObservations(input: string): ConvertibleResearch['observations'] {
  const lines = input.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
  if (lines[0] === 'date,stock_close,conversion_price') lines.shift()
  if (lines.length > 260) throw new Error('观察记录最多 260 个交易日')
  const dates = new Set<string>()
  return lines.map((line, index) => {
    const fields = line.split(',').map(value => value.trim())
    if (fields.length !== 3) throw new Error(`观察记录第 ${index + 1} 行须有日期、正股收盘价、当日转股价三列`)
    const date = dateValue(fields[0], `观察记录第 ${index + 1} 行`)
    if (dates.has(date)) throw new Error(`观察记录日期 ${date} 重复`)
    dates.add(date)
    return { date, stock_close: positive(fields[1], '正股不复权收盘价'), conversion_price: positive(fields[2], '当日有效转股价') }
  })
}
export function buildResearch(draft: ResearchDraft): ConvertibleResearch {
  const interest = optionalNumber(draft.accrued_interest, '应计利息')
  if (interest != null && interest < 0) throw new Error('应计利息不能小于零')
  const events = draft.events.map((event, index) => {
    const date = dateValue(event.date, `公告第 ${index + 1} 项日期`)
    if (!event.title.trim()) throw new Error(`公告第 ${index + 1} 项需要填写标题`)
    const source = event.source_url?.trim() || null
    if (source) { let url: URL; try { url = new URL(source) } catch { throw new Error(`公告第 ${index + 1} 项来源链接格式不正确`) } if (!['http:', 'https:'].includes(url.protocol)) throw new Error('公告来源只接受 http 或 https 链接') }
    return { ...event, date, title: event.title.trim(), source_url: source, note: event.note?.trim() || null }
  })
  return {
    cash_flows: cashFlows(draft.cash_flows, '到期现金流'), put_cash_flows: cashFlows(draft.put_cash_flows, '回售现金流'),
    calculation_settings: draft.calculation_settings,
    personal_rating: draft.personal_rating,
    parameter_note: draft.parameter_note,
    fund_holding_report_date: draft.fund_holding_report_date,
    cash_flows_complete: draft.cash_flows_complete, put_cash_flows_complete: draft.put_cash_flows_complete,
    price_basis: draft.price_basis || null, accrued_interest: interest,
    discount_rate_pct: optionalNumber(draft.discount_rate_pct, '纯债折现率'), risk_free_rate_pct: optionalNumber(draft.risk_free_rate_pct, '无风险利率'), dividend_yield_pct: optionalNumber(draft.dividend_yield_pct, '股息率'),
    call_clause: clauseValue(draft.call_clause, '强赎'), put_clause: clauseValue(draft.put_clause, '回售'),
    observations: parseObservations(draft.observations), observations_as_of: draft.observations_as_of, events,
  }
}
