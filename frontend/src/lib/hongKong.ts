/** Hong Kong securities use an explicit market suffix, never a six-digit A-share guess. */
export function isHongKongSymbol(symbol: string): boolean {
  return /^\d{5}\.HK$/i.test(symbol)
}

export function isInternationalSymbol(symbol: string): boolean {
  return /^(?:[A-Z][A-Z0-9.-]{0,14}\.US|\d{4}\.JP)$/i.test(symbol)
}
export function isExternalSymbol(symbol: string): boolean {
  return isHongKongSymbol(symbol) || isInternationalSymbol(symbol)
}
export function marketType(symbol: string): 'hk' | 'us' | 'jp' {
  return symbol.endsWith('.US') ? 'us' : symbol.endsWith('.JP') ? 'jp' : 'hk'
}
export function marketLabel(symbol: string): string {
  return ({ hk: '港股', us: '美股', jp: '日股' })[marketType(symbol)]
}
