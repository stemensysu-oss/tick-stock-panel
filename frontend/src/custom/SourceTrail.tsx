const SOURCES: Record<string, string> = { tickflow: 'TickFlow', fuyao: '扶摇', eastmoney_public: '东方财富公开补充源', eastmoney_events_public: '东方财富公开事件', tencent_public: '腾讯公开补充行情', sina_tencent_public: '公开备用目录与行情', sse_public: '上交所公开资格目录', sse_dated_catalog: '交易所历史代码目录', aastocks_public: 'AASTOCKS 公开配对目录', aastocks_directory_snapshot: '公开配对历史代码目录' }
const STATES: Record<string, string> = { success: '返回数据', empty: '无有效数据', unconfigured: '未配置', unsupported: '当前未集成此数据集', failed: '请求失败' }
const DATASETS: Record<string, string> = { t0_eligibility: '回转资格', ah_pairs: 'A/H 配对', fx_hkd_cny: '港元兑人民币汇率', ah_quotes: '两地报价', quote_currency: '报价币种' }

export function SourceTrail({ data }: { data?: { provider?: string; attempts?: { provider: string; status: string; dataset?: string; operation?: string }[]; warnings?: string[] } }) {
  if (!data) return null
  return <div className="space-y-1 border-t border-border px-4 py-3 text-[11px] leading-relaxed text-muted">
    {data.provider && <p>实际来源：{SOURCES[data.provider] || data.provider}</p>}
    {!!data.attempts?.length && <p>取数顺序：{data.attempts.map(attempt => { const dataset = DATASETS[attempt.dataset || attempt.operation || '']; return `${SOURCES[attempt.provider] || attempt.provider}${dataset ? ` · ${dataset}` : ''}（${STATES[attempt.status] || attempt.status}）` }).join(' → ')}</p>}
    {data.warnings?.map((warning, index) => <p key={index}>{warning}</p>)}
  </div>
}
