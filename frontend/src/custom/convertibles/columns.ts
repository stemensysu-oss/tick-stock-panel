import type { ConvertibleItem } from '@/lib/api'

export type ColumnId = 'pure_bond_value_basis' | 'pure_bond_value_date' | 'maturity_redemption_price' | 'code' | 'name' | 'bond_price' | 'bond_change_pct' | 'stock_code' | 'stock_name' | 'stock_price' | 'stock_change_pct' | 'stock_pb' | 'conversion_price' | 'conversion_value' | 'conversion_premium_pct' | 'double_low' | 'pure_bond_value' | 'credit_rating' | 'option_value' | 'stock_volatility_pct' | 'put_trigger_price' | 'call_trigger_price' | 'debt_to_float_cap_pct' | 'fund_holding_pct' | 'maturity_date' | 'remaining_years' | 'outstanding_amount' | 'turnover_amount' | 'turnover_rate_pct' | 'ytm_pct' | 'put_yield_pct'
export interface ConvertibleColumn { id: ColumnId; label: string; group: string; unit?: string; digits?: number; divisor?: number; description?: string }
export const COLUMNS: ConvertibleColumn[] = [
  { id: 'code', label: '代码', group: '基础' },
  { id: 'name', label: '转债名称', group: '基础' },
  { id: 'bond_price', label: '现价', unit: '元', digits: 3, group: '行情' },
  { id: 'bond_change_pct', label: '涨跌幅', unit: '%', group: '行情' },
  { id: 'stock_code', label: '正股代码', group: '正股' },
  { id: 'stock_name', label: '正股名称', group: '正股' },
  { id: 'stock_price', label: '正股价', unit: '元', group: '正股' },
  { id: 'stock_change_pct', label: '正股涨跌', unit: '%', group: '正股' },
  { id: 'stock_pb', label: '正股 PB', group: '正股', description: '市净率；允许负值，须结合净资产口径和数据日期。' },
  { id: 'conversion_price', label: '转股价', unit: '元', group: '转股' },
  { id: 'conversion_value', label: '转股价值', unit: '元', group: '转股' },
  { id: 'conversion_premium_pct', label: '转股溢价率', unit: '%', group: '转股' },
  { id: 'double_low', label: '双低值', group: '转股', description: '转债现价 + 转股溢价率百分数，不是预期收益率。' },
  { id: 'pure_bond_value', label: '纯债价值', unit: '元', group: '模型', description: '手工模型优先，否则展示带日期的公开估值；供应商折现曲线未披露，不是保本价格。' },
  { id: 'pure_bond_value_basis', label: '纯债口径', group: '模型' },
  { id: 'pure_bond_value_date', label: '纯债估值日', group: '模型' },
  { id: 'maturity_redemption_price', label: '到期赎回价', unit: '元', group: '条款', description: '公开源参考总额，是否包含末期利息须核对条款，不能重复加息。' },
  { id: 'credit_rating', label: '评级', group: '基础' },
  { id: 'option_value', label: '期权价值', unit: '元', group: '模型', description: '简化 B-S 欧式期权模型值，不包含全部可转债条款。' },
  { id: 'stock_volatility_pct', label: '正股波动率', unit: '%', group: '模型', description: '输入的年化波动率；窗口与复权方式在详情中展示。' },
  { id: 'put_trigger_price', label: '回售触发价', unit: '元', group: '条款' },
  { id: 'call_trigger_price', label: '强赎触发价', unit: '元', group: '条款' },
  { id: 'debt_to_float_cap_pct', label: '本金/流通市值', unit: '%', group: '基础', description: '剩余债券本金 ÷ 正股流通市值 × 100%，不使用转债交易市值。' },
  { id: 'fund_holding_pct', label: '基金持有', unit: '%', group: '基础', description: '所提供报告期的基金持有本金占剩余本金比例；不代表实时全量持仓。' },
  { id: 'maturity_date', label: '到期日期', group: '条款', description: '人工资料优先，否则为公开参考到期日；转股截止、退市日期另列。' },
  { id: 'remaining_years', label: '剩余年限', unit: '年', group: '条款', description: '距到期日的自然日数 / 365。' },
  { id: 'outstanding_amount', label: '剩余规模', unit: '亿元', divisor: 100_000_000, group: '基础', description: '尚未转股的债券本金，不是发行规模或市场价值。' },
  { id: 'turnover_amount', label: '成交额', unit: '万元', divisor: 10_000, group: '行情' },
  { id: 'turnover_rate_pct', label: '换手率', unit: '%', group: '行情' },
  { id: 'ytm_pct', label: '到期税前收益', unit: '%', group: '模型', description: '完整日期现金流的 ACT/365 年复利内部收益率，不沿用其他网站的短期年化口径。' },
  { id: 'put_yield_pct', label: '回售情景收益', unit: '%', group: '模型', description: '按明确回售情景现金流计算，不代表回售权已经生效。' },
]
export const DEFAULT_COLUMNS: ColumnId[] = ['code', 'name', 'bond_price', 'bond_change_pct', 'stock_name', 'stock_price', 'conversion_price', 'conversion_value', 'conversion_premium_pct', 'double_low', 'pure_bond_value', 'pure_bond_value_basis', 'pure_bond_value_date', 'credit_rating', 'maturity_date', 'remaining_years', 'maturity_redemption_price', 'outstanding_amount', 'ytm_pct']
export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
export function formatColumn(item: ConvertibleItem, column: ConvertibleColumn): string {
  const value = item[column.id]
  if (value == null || value === '') return '—'
  return typeof value === 'number' ? formatNumber(value / (column.divisor ?? 1), column.digits ?? 2) : String(value)
}
export const BUTTON = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border px-2 py-1.5 text-xs font-medium transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40'
export const INPUT = 'h-7 min-w-0 w-full rounded-input border border-border bg-base px-3 text-xs outline-none focus:border-accent disabled:opacity-50'
export function safeSourceUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null } catch { return null }
}
