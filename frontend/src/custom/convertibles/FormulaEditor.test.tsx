// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { FormulaEditor, emptySettings } from './FormulaEditor'
import type { ConvertibleItem } from '@/lib/api'

vi.mock('@/lib/api', () => ({ api: { convertibleFormulaCatalog: async () => ({
  formulas: [{ id: 'pure_bond_value', label: '个人纯债', unit: '元', formula: 'PV(discount_rate_pct, day_count_basis)' }],
  inputs: [{ id: 'discount_rate_pct', label: '折现率', unit: '%', editable: true }],
  functions: ['PV'], function_docs: [{ name: 'PV(r,b)', formula: 'Σ CF/(1+r/100)^(d/b)', note: '年有效利率' }], conventions: [],
}) } }))

it('参数与公式是草稿，恢复继承且展示缺项及公开值独立来源', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const client = new QueryClient()
  const changed = vi.fn()
  const item = { calculation_details: { pure_bond_value: { label: '个人纯债', unit: '元', formula: 'PV(discount_rate_pct, day_count_basis)', result: null, inputs: { discount_rate_pct: null }, missing: ['discount_rate_pct'], status: 'missing', custom: false, source: '默认公式' } } } as unknown as ConvertibleItem
  function Harness() {
    const [value, setValue] = useState(emptySettings())
    return <FormulaEditor value={value} onChange={next => { setValue(next); changed(next) }} item={item} reference={{ pure_bond_value: 98, valuation_date: '2026-10-23' } as never} />
  }
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>))
    for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
    expect(host.textContent).toContain('缺少输入')
    expect(host.textContent).toContain('独立公开参考 98.0000')
    expect(changed).not.toHaveBeenCalled()
    const expression = host.querySelector('textarea')!
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(expression, 'PV(5)'); expression.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ formulas: { pure_bond_value: 'PV(5)' } }))
    const reset = [...host.querySelectorAll('button')].find(button => button.textContent === '恢复继承公式')!
    await act(async () => reset.click())
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ formulas: {} }))
    const parameter = host.querySelector('input[type="number"]')!
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(parameter, '0'); parameter.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ parameters: { discount_rate_pct: 0 } }))
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(parameter, ''); parameter.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ parameters: {} }))
  } finally { await act(async () => root.unmount()); client.clear(); host.remove() }
})
