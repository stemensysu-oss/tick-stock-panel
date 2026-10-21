import { describe, expect, it } from 'vitest'
import { blankClause, buildResearch, createResearchDraft, parseObservations } from './researchForm'
import { csvCell, createConvertibleCsv } from './export'
import type { ConvertibleItem } from '@/lib/api'

describe('研究资料表单数据边界', () => {
  it('空资料不假设已确认现金流、全价或常见强赎条款', () => {
    const research = buildResearch(createResearchDraft())
    expect(research.price_basis).toBeNull()
    expect(research.cash_flows_complete).toBe(false)
    expect(research.call_clause).toBeNull()
    expect(research.risk_free_rate_pct).toBeNull()
    expect(research.observations_as_of).toBeNull()
  })
  it('百分数和现金流原样传给后端，零利率不被丢失', () => {
    const draft = createResearchDraft()
    draft.price_basis = 'clean'; draft.accrued_interest = '0.6'
    draft.cash_flows = [{ date: '2027-10-21', amount: '110' }]
    draft.cash_flows_complete = true; draft.risk_free_rate_pct = '0'; draft.discount_rate_pct = '3'
    const research = buildResearch(draft)
    expect(research.cash_flows).toEqual([{ date: '2027-10-21', amount: 110 }])
    expect(research.risk_free_rate_pct).toBe(0)
    expect(research.discount_rate_pct).toBe(3)
    expect(research.accrued_interest).toBe(0.6)
    expect('ytm_pct' in research).toBe(false)
  })
  it('同日重复现金流、无效日期及不安全公告链接阻止提交', () => {
    const draft = createResearchDraft()
    draft.cash_flows = [{ date: '2027-10-21', amount: '110' }, { date: '2027-10-21', amount: '2' }]
    expect(() => buildResearch(draft)).toThrow('同一天的款项请先合并')
    draft.cash_flows = [{ date: '2027-02-30', amount: '110' }]
    expect(() => buildResearch(draft)).toThrow('有效的')
    draft.cash_flows = []
    draft.events = [{ date: '2026-10-21', type: 'call', title: '事件', source_url: 'javascript:alert(1)' }]
    expect(() => buildResearch(draft)).toThrow('http 或 https')
  })
  it('交易日观察拒绝重复日期和缺列，不用自然日自动补齐', () => {
    expect(parseObservations('date,stock_close,conversion_price\n2026-10-20,13,10\n2026-10-21,12,9')).toEqual([{ date: '2026-10-20', stock_close: 13, conversion_price: 10 }, { date: '2026-10-21', stock_close: 12, conversion_price: 9 }])
    expect(() => parseObservations('2026-10-21,12,10\n2026-10-21,13,10')).toThrow('重复')
    expect(() => parseObservations('2026-10-21,12')).toThrow('三列')
    const draft = createResearchDraft(); draft.call_clause = { ...blankClause(), window_days: '30', required_days: '31', trigger_ratio_pct: '130' }
    expect(() => buildResearch(draft)).toThrow('不能超过窗口')
  })
})

describe('研究数据导出', () => {
  it('文本公式被中和，负收益率仍保持数值，金额保持元单位', () => {
    expect(csvCell('=HYPERLINK("https://example.test")')).toBe('"\'=HYPERLINK(""https://example.test"")"')
    expect(csvCell(-12.5)).toBe('"-12.5"')
    const row = { code: '000001', name: '@恶意公式', outstanding_amount: 300000000, ytm_pct: -12.5 } as ConvertibleItem
    const csv = createConvertibleCsv([row], ['code', 'name', 'outstanding_amount', 'ytm_pct'])
    expect(csv).toContain('"300000000"')
    expect(csv).toContain('"\'@恶意公式"')
    expect(csv).not.toContain('research')
  })
})
