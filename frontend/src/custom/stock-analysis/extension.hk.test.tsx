// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StockAnalysis } from './extension'
const mocks=vi.hoisted(()=>({search:vi.fn(),hk:vi.fn(),daily:vi.fn(),levels:vi.fn(),ai:vi.fn(),chart:vi.fn()}))
vi.mock('@/lib/api',async original=>{const actual=await original<typeof import('@/lib/api')>();return {...actual,api:{...actual.api,instrumentSearch:mocks.search,stockAnalysisHk:mocks.hk,hkFundamentals:async()=>({symbol:"00700.HK",status:"unavailable",tables:{},warnings:[],references:[],fetched_at:"test"}),japanSource:async()=>({configured:false}),klineDaily:mocks.daily,stockAnalysisLevels:mocks.levels}}})
vi.mock('@/lib/useLastStock',()=>({useLastStock:()=>({last:null,remember:vi.fn()})}))
vi.mock('@/lib/stockAnalysisStore',()=>({startAnalysis:mocks.ai,findTodayReport:async()=>null,useHistoryReports:()=>({reports:[],loaded:true}),loadHistory:vi.fn(),deleteReport:vi.fn(),openHistoryReport:vi.fn()}))
vi.mock('@/components/StockPreviewDialog',()=>({StockPreviewDialog:()=>null}))
vi.mock('@/components/stock-analysis/PriceAlertDialog',()=>({PriceAlertDialog:()=>null}))
vi.mock('@/components/stock-analysis/AnalysisKChart',()=>({AnalysisKChart:(props:any)=>{mocks.chart(props);return <div data-testid="chart"/>}}))
const data={symbol:'00700.HK',name:'腾讯控股',currency:'HKD',rows:[{date:'2026-10-21',open:400,high:410,low:390,close:395,volume:100}],as_of:'2026-10-21',close:395,levels:{pivot:[{value:399,type:'pivot',label:'P'}]},series:{},dates:['2026-10-21'],source_name:'公开补充',fetched_at:'2026-10-22',quote:{close:382,change_pct:-.03,quote_at:'2026-10-22T15:00:00+08:00',quote_source:'公开报价'},warnings:['港股财务与直接新闻未接入']}
let host:HTMLDivElement,root:Root,client:QueryClient
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();localStorage.clear();host=document.createElement('div');document.body.append(host);root=createRoot(host);client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});mocks.hk.mockResolvedValue(data);mocks.ai.mockResolvedValue({});mocks.search.mockResolvedValue({results:[{symbol:'00700.HK',code:'00700',name:'腾讯控股',asset_type:'hk'}],warnings:['来源建议']})})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();host.remove()})
async function settle(){await act(async()=>{await new Promise(r=>setTimeout(r,40))})}
async function choose(query='00700', symbol='00700.HK'){
 await act(async()=>root.render(<QueryClientProvider client={client}><MemoryRouter><StockAnalysis/></MemoryRouter></QueryClientProvider>));const input=host.querySelector('input')!
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,query);input.dispatchEvent(new Event('input',{bubbles:true}))});await settle()
 const button=Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes(symbol))!;await act(async()=>button.click());await settle()
}
it('search select chart levels and AI use complete HK symbol; mainland and alerts excluded',async()=>{
 await choose();expect(mocks.search).toHaveBeenCalledWith('00700',20,'stock,index,hk,us,jp');expect(mocks.hk).toHaveBeenCalledWith('00700.HK');expect(mocks.daily).not.toHaveBeenCalled();expect(mocks.levels).not.toHaveBeenCalled();expect(mocks.chart.mock.lastCall?.[0].levels.pivot[0].value).toBe(399);expect(host.textContent).toContain('395.00 HKD');expect(host.textContent).toContain('财务与直接新闻未接入');const button=Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes('AI 港股研究分析'))!;await act(async()=>button.click());await settle();expect(mocks.ai).toHaveBeenCalledWith('00700.HK','腾讯控股');expect(host.textContent).not.toContain('点位提醒')
})
it('alias uses same code and forced refresh failure retains chart',async()=>{await choose('腾讯科技');mocks.hk.mockRejectedValue(new Error('offline'));const button=Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes('刷新港股分析数据'))!;await act(async()=>button.click());await settle();expect(mocks.hk).toHaveBeenCalledWith('00700.HK',true);expect(host.textContent).toContain('原有数据保留');expect(host.textContent).toContain('395.00 HKD');expect(host.querySelector('[data-testid="chart"]')).not.toBeNull()})
it('HK failure never falls through to mainland',async()=>{mocks.hk.mockRejectedValue(new Error('unavailable'));await choose();expect(host.textContent).toContain('读取失败');expect(mocks.daily).not.toHaveBeenCalled();expect(mocks.chart).not.toHaveBeenCalled()})

it.each([['AAPL','AAPL.US','USD','美股'],['7203','7203.JP','JPY','日股']])('international select %s keeps market data separate',async(query,symbol,currency,label)=>{
 mocks.search.mockResolvedValue({results:[{symbol,code:query,name:query,asset_type:symbol.endsWith('.US')?'us':'jp'}]})
 mocks.hk.mockResolvedValue({...data,symbol,currency,name:query,quote:{...data.quote,currency},warnings:['历史收盘，不是实时行情']})
 await choose(query,symbol)
 expect(mocks.hk).toHaveBeenCalledWith(symbol)
 expect(host.textContent).toContain(`395.00 ${currency}`)
 expect(host.textContent).toContain('不是实时行情')
 expect(host.textContent).not.toContain('点位提醒')
 const button=Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes(`AI ${label}技术分析`))!
 await act(async()=>button.click()); await settle()
 expect(mocks.ai).toHaveBeenCalledWith(symbol,query)
 expect(mocks.daily).not.toHaveBeenCalled()
 if(currency==='JPY') expect(host.textContent).toContain('延迟12周')
})
