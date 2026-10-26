import type { ConvertibleItem, ConvertibleReference } from '@/lib/api'

/** Presentation only. Never pass these overlays into JSON research backups. */
export function withReference(item: ConvertibleItem, ref: ConvertibleReference | undefined, asOf: string | null): ConvertibleItem {
  const calculated = Boolean(item.calculation_details && Object.keys(item.calculation_details).length)
  const modelBasis = calculated ? `个人${item.calculation_details?.pure_bond_value?.custom ? '自定义' : '默认'}公式` : '手工模型试算'
  if (!ref) return { ...item,
    pure_bond_value_basis: item.pure_bond_value != null ? modelBasis : null,
    pure_bond_value_date: item.pure_bond_value != null ? asOf : null,
  }
  const maturity = item.maturity_date ?? ref.maturity_date
  const years = maturity && asOf ? Math.max(0, (Date.parse(maturity) - Date.parse(asOf)) / 86_400_000 / 365) : null
  return { ...item,
    maturity_date: maturity,
    remaining_years: calculated ? item.remaining_years : item.remaining_years ?? years,
    credit_rating: item.credit_rating ?? ref.credit_rating,
    conversion_start_date: item.conversion_start_date ?? ref.conversion_start_date,
    listing_date: item.listing_date ?? ref.listing_date,
    pure_bond_value: item.pure_bond_value ?? ref.pure_bond_value,
    pure_bond_value_basis: item.pure_bond_value != null ? modelBasis : ref.pure_bond_value != null ? '公开模型参考' : null,
    pure_bond_value_date: item.pure_bond_value != null ? asOf : ref.valuation_date,
    maturity_redemption_price: ref.maturity_redemption_price,
    call_trigger_price: calculated ? item.call_trigger_price : item.call_trigger_price ?? ref.call_trigger_price,
    put_trigger_price: calculated ? item.put_trigger_price : item.put_trigger_price ?? ref.put_trigger_price,
  }
}

export function referenceHint(item: ConvertibleItem): string | undefined {
  return item.pure_bond_value_basis ? `${item.pure_bond_value_basis} · 数据日 ${item.pure_bond_value_date ?? '未知'}；与当日行情可能不同，非保本价格` : undefined
}
