import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { QK } from '@/lib/queryKeys'
import { api } from '@/lib/api'

export function JapanSourceSettings({ onSaved }: { onSaved: () => void }) {
  const [key, setKey] = useState('')
  const source = useQuery({ queryKey: QK.japanSource, queryFn: api.japanSource })
  const save = useMutation({ mutationFn: () => api.saveJapanSource(key), onSuccess: () => {
    setKey(''); void source.refetch(); onSaved()
  } })
  return <div className="my-4 rounded border border-border p-3 space-y-2">
    <p>可选个人备用源：J-Quants V2 · {source.data?.configured ? '已配置个人密钥' : '未配置（可先用公开补充源）'}</p>
    <p className="text-xs text-muted">公开补充源可用时无需密钥。J-Quants免费计划延迟12周，近期日线需相应套餐；所有日线均为日终数据。使用你本人订阅的密钥，保存在此电脑，不随安装包分发。</p>
    <a className="text-xs text-accent" href="https://jpx-jquants.com/" target="_blank" rel="noreferrer">打开 J-Quants</a>
    <div className="flex flex-wrap gap-2"><input type="password" value={key} onChange={e => setKey(e.target.value)} autoComplete="off" aria-label="J-Quants个人密钥" placeholder="输入个人 API Key" className="min-w-0 flex-1 rounded border border-border bg-elevated p-2" />
      <button disabled={!key.trim() || save.isPending} onClick={() => save.mutate()} className="rounded border border-border px-3 disabled:opacity-50">{save.isPending ? '保存中…' : '保存并读取日股'}</button></div>
    {(source.isError || save.isError) && <p role="alert" className="text-xs text-warning">配置读取或保存失败，请重试；原有设置保留。</p>}
    <p className="text-xs text-muted">日股 AI 分析会向你配置的模型发送所列数据，请使用符合个人数据许可、隐私和不训练要求的服务。</p>
  </div>
}
