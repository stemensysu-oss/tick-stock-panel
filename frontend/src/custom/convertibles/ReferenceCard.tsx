import type { ConvertibleReference } from '@/lib/api'
import { formatNumber, safeSourceUrl } from './columns'

export function ReferenceCard({ data }: { data?: ConvertibleReference }) {
  if (!data) return <p className="text-xs text-muted">公开参考资料尚未取得。可在主表点击“补齐条款与估值”；现金流与估值中的手工试算可独立使用。</p>
  const url = safeSourceUrl(data.source_url)
  return <section aria-label="公开条款与估值参考" className="space-y-3 rounded-card border border-border p-4">
    <h3 className="text-sm font-semibold">公开条款与估值参考</h3>
    <p className="text-xs leading-relaxed text-muted">与保存的手工试算分开展示。公开纯债模型的折现曲线、净价/全价口径未披露；不代表保本价格。</p>
    <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">{[
      ['到期日期（参考）', data.maturity_date ?? '未确认'], ['转股截止', data.conversion_end_date ?? '未知'],
      ['纯债价值（元/张）', formatNumber(data.pure_bond_value, 4)], ['估值数据日', data.valuation_date ?? '未知'],
      ['同日收盘价（元）', formatNumber(data.valuation_close, 3)], ['同日纯债溢价率（%）', formatNumber(data.pure_bond_premium_pct)],
      ['到期赎回价（元/张）', formatNumber(data.maturity_redemption_price)], ['评级（公开资料）', data.credit_rating ?? '未知'],
      ['评级机构', data.rating_agency ?? '未知'],
      ['剩余规模（亿元）', data.outstanding_amount == null ? '未知' : formatNumber(data.outstanding_amount / 100_000_000, 4)],
      ['存续数量（张）', formatNumber(data.outstanding_units, 0)],
      ['正股PB', formatNumber(data.stock_pb)], ['正股流通市值（亿元）', data.float_market_cap == null ? '未知' : formatNumber(data.float_market_cap / 100_000_000)],
      ['生命周期', data.lifecycle === 'terminated' ? '已终止 / 退市' : data.lifecycle === 'listed' ? '已上市' : '未确认'],
    ].map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd className="mt-1.5 font-mono">{value}</dd></div>)}</dl>
    {data.outstanding_basis && <p className="text-xs text-muted">{data.outstanding_basis}。观察时间 {data.outstanding_observed_at}；来源未提供余额统计日，不能当作历史时点数据。</p>}
    {data.coupon_text && <p className="text-xs leading-relaxed">票息：{data.coupon_text}</p>}
    {data.warnings.map(w => <p key={w} className="text-xs text-warning">{w}</p>)}
    <p className="text-[11px] text-muted">来源 {data.source} · 获取于 {data.fetched_at}；获取时间不是公告日。{url && <a href={url} target="_blank" rel="noopener noreferrer" className="ml-2 text-accent">查看原页</a>}</p>
  </section>
}
