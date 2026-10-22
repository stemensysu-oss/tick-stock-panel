// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { EChartsOption } from 'echarts'
import { expect, it, vi } from 'vitest'
import { FundNavChart } from './FundNavChart'

const captured = vi.hoisted(() => ({ option: null as EChartsOption | null }))
vi.mock('@/pages/backtest/charts/useECharts', () => ({ useECharts: (option: EChartsOption) => { captured.option = option; return { current: null } } }))

it('缺值之间唯一的有效净值保留可见点，不跨缺值连线或补零', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(<FundNavChart field="unit_nav" items={[
      { date: '2026-10-19', unit_nav: null, adj_nav: null },
      { date: '2026-10-20', unit_nav: 1.2345, adj_nav: null },
      { date: '2026-10-21', unit_nav: null, adj_nav: null },
    ]} />))
    expect(captured.option?.series).toEqual(expect.arrayContaining([expect.objectContaining({
      data: [null, 1.2345, null], showSymbol: true, showAllSymbol: true, connectNulls: false,
    })]))
  } finally { await act(async () => root.unmount()) }
})

it('货币收益字段未提供时不计作有效点，稀疏公布的万份收益仍保留可见点', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div')
  const root = createRoot(host)
  const items = Array.from({ length: 40 }, (_, i) => ({ date: new Date(Date.UTC(2026, 8, 1 + i)).toISOString().slice(0, 10), unit_nav: null, adj_nav: null,
    ...(i === 20 ? { income_per_10000: 0.31 } : {}),
  }))
  try {
    await act(async () => root.render(<FundNavChart field="income_per_10000" items={items} />))
    expect(captured.option?.series).toEqual(expect.arrayContaining([expect.objectContaining({
      data: items.map((_, i) => i === 20 ? 0.31 : null), showAllSymbol: true, connectNulls: false,
    })]))
  } finally { await act(async () => root.unmount()) }
})
