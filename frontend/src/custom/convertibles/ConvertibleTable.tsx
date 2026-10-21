import type { ConvertibleItem } from '@/lib/api'

function number(value: number | null, digits = 2) {
  return value === null ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function ConvertibleTable({ items, caption }: { items: ConvertibleItem[]; caption: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1120px] text-xs">
        <caption className="sr-only">{caption}；价格单位元，溢价率为百分数，缺失数据以横线显示</caption>
        <thead className="border-y border-border bg-elevated/50 text-right text-[11px] text-muted"><tr>
          <th className="sticky left-0 z-10 min-w-36 bg-surface px-4 py-3 text-left font-medium">转债 / 正股</th>
          {['转债现价', '正股价', '转股价', '面值', '转股价值', '转股溢价率', '双低值', '到期日', '强赎状态'].map(label => <th className="whitespace-nowrap px-3 py-3 font-medium" key={label}>{label}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-border/60">{items.map(item => <tr key={item.code} className="group text-right hover:bg-elevated/20">
          <td className="sticky left-0 z-10 bg-surface px-4 py-3 text-left group-hover:bg-elevated"><div className="font-medium text-foreground">{item.name}</div><div className="mt-1 font-mono text-[10px] text-muted">{item.code}</div><div className="mt-1 max-w-44 truncate text-[10px] text-secondary" title={[item.stock_name, item.stock_code].filter(Boolean).join(' ')}>{item.stock_name || item.stock_code || '正股未提供'}</div></td>
          <td className="px-3 py-3 font-mono tabular-nums text-foreground">{number(item.bond_price)}</td>
          <td className="px-3 py-3 font-mono tabular-nums text-secondary">{number(item.stock_price)}</td>
          <td className="px-3 py-3 font-mono tabular-nums text-secondary">{number(item.conversion_price)}</td>
          <td className="px-3 py-3 font-mono tabular-nums text-muted">{number(item.face_value)}</td>
          <td className="px-3 py-3 font-mono tabular-nums">{number(item.conversion_value)}</td>
          <td className="px-3 py-3 font-mono tabular-nums">{item.conversion_premium_pct === null ? '—' : `${number(item.conversion_premium_pct)}%`}</td>
          <td className="px-3 py-3 font-mono font-semibold tabular-nums text-accent">{number(item.double_low)}</td>
          <td className="whitespace-nowrap px-3 py-3 font-mono text-secondary">{item.maturity_date || '—'}</td>
          <td className="max-w-56 px-3 py-3"><span className={item.redemption_status ? 'text-secondary' : 'text-muted'}>{item.redemption_status || '未知'}</span></td>
        </tr>)}</tbody>
      </table>
    </div>
  )
}
