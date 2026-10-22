/** Hong Kong securities use an explicit market suffix, never a six-digit A-share guess. */
export function isHongKongSymbol(symbol: string): boolean {
  return /^\d{5}\.HK$/i.test(symbol)
}
