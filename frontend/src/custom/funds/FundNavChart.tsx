import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import type { FundNavItem } from '@/lib/api'
import { useChartTheme } from '@/lib/theme'
import { useECharts } from '@/pages/backtest/charts/useECharts'

export function FundNavChart({ items, field }: { items: FundNavItem[]; field: 'unit_nav' | 'adj_nav' }) {
  const theme = useChartTheme()
  const name = field === 'unit_nav' ? '单位净值' : '复权净值'
  const option = useMemo<EChartsOption>(() => ({
    animation: false,
    grid: { left: 60, right: 20, top: 20, bottom: 48 },
    tooltip: {
      trigger: 'axis', backgroundColor: theme.tooltipBg, borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText },
      valueFormatter: value => value == null ? '—' : Number(value).toFixed(4),
    },
    xAxis: {
      type: 'category', data: items.map(item => item.date), boundaryGap: false,
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false }, axisLabel: { color: theme.text, hideOverlap: true },
    },
    yAxis: {
      type: 'value', scale: true, axisLabel: { color: theme.text },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    series: [{
      name, type: 'line', data: items.map(item => item[field]),
      // 稀疏数据的孤立点始终可见；密集数据交给图表控密度，缺值两侧不连线。
      showSymbol: true, showAllSymbol: items.filter(item => item[field] !== null).length <= 32 ? true : 'auto',
      symbolSize: 4, connectNulls: false,
      lineStyle: { width: 2, color: '#3b82f6' }, itemStyle: { color: '#3b82f6' },
      areaStyle: { color: 'rgba(59,130,246,0.07)' },
    }],
  }), [items, field, name, theme])
  const chartRef = useECharts(option)
  return <div ref={chartRef} role="img" aria-label={`${name}走势图，横轴为净值日期，纵轴为净值（源币种）`} className="h-72 w-full sm:h-80" />
}
