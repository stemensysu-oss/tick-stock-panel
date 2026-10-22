const SOURCES: Record<string, string> = { tickflow: 'TickFlow', fuyao: '扶摇', eastmoney_public: '东方财富公开补充源' }
const STATES: Record<string, string> = { success: '返回数据', empty: '无有效数据', unconfigured: '未配置', unsupported: '当前未集成此数据集', failed: '请求失败' }

export function SourceTrail({ data }: { data?: { provider?: string; attempts?: { provider: string; status: string }[]; warnings?: string[] } }) {
  if (!data) return null
  return <div className="space-y-1 border-t border-border px-4 py-3 text-[11px] leading-relaxed text-muted">
    {data.provider && <p>实际来源：{SOURCES[data.provider] || data.provider}</p>}
    {!!data.attempts?.length && <p>取数顺序：{data.attempts.map(attempt => `${SOURCES[attempt.provider] || attempt.provider}（${STATES[attempt.status] || attempt.status}）`).join(' → ')}</p>}
    {data.warnings?.map((warning, index) => <p key={index}>{warning}</p>)}
  </div>
}
