import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useApi, post, http, qc } from '../api'
import { Chip, Icon, Notice, Empty, Skel } from '../ui'
import { Markdown } from '../md'
import { HeroButton, Mascot, Ring } from '../fx'

const EXAMPLES: [string, string][] = [
  ['Who should I start this week?', 'Who should I start this week and why?'],
  ['Find me a trade', 'Scan the whole league for a trade that helps my lineup, slightly in my favor (about 60/40 in my value), that the other manager would plausibly accept. Show the offer ladder.'],
  ['Any waiver moves?', 'Do I need any add/drop or streaming move this week? If not, say so.'],
  ['Is anyone injured?', 'Is anyone on my team injured or on a bye, and what should I do?'],
]

export function MoveCards({ moves }: { moves: any }) {
  const C: Record<string, [string, string]> = { high: ['good', 'verified'], medium: ['', 'help'], low: ['warn', 'warning'] }
  return (
    <>
      {moves.moves?.map((m: any, i: number) => (
        <div key={i} className="mv"><Ring value={{ high: 0.95, medium: 0.6, low: 0.3 }[m.confidence as string] ?? 0.5} size={44} label={`${m.confidence} confidence`}><span className="sr-only">{m.confidence}</span></Ring><div className="h"><b>Add {m.add}{m.drop ? `, drop ${m.drop}` : ''}</b><span className="num">{m.gain_this_week >= 0 ? '+' : ''}{m.gain_this_week} this week · {m.gain_rest_of_season >= 0 ? '+' : ''}{m.gain_rest_of_season} rest of season</span></div>
          <div className="ctxrow"><Chip kind={C[m.confidence][0]} icon={C[m.confidence][1]}>{m.confidence[0].toUpperCase() + m.confidence.slice(1)} confidence</Chip>{m.flags.includes('speculative') && <Chip kind="warn" icon="bolt">Speculative</Chip>}</div>
          <details className="exp"><summary>Why</summary><div>{m.reason}</div></details></div>))}
      {moves.streaming?.map((s: any, i: number) => <Notice key={i} kind={s.swap ? '' : 'good'} icon={s.swap ? 'autorenew' : 'check_circle'}><b>{s.swap ? `Stream ${s.position}: add ${s.best}${s.current ? `, drop ${s.current}` : ''}` : `Keep your current ${s.position} (${s.current})`}</b>. {s.reason}</Notice>)}
      {moves.no_move_needed && <Notice kind="good" icon="check_circle"><b>No move needed.</b> {moves.no_move_reason}</Notice>}
    </>
  )
}

export function Msg({ m }: { m: any }) {
  return (
    <div className={`msg ${m.role}`}>
      <Markdown text={m.text} />
      {m.trace?.filter((t: any) => t.moves).map((t: any, i: number) => <MoveCards key={i} moves={t.moves} />)}
      {m.trace?.length > 0 && <details className="exp"><summary>What I looked up ({m.trace.length})</summary>{m.trace.map((t: any, i: number) => <div key={i} className="tool"><Icon n="data_object" /> {t.tool}({t.input}){t.error ? ' - failed' : ''}</div>)}</details>}
    </div>
  )
}

export default function Assistant() {
  const { data: d, isLoading } = useApi<any>('/api/chat', { stale: 0 })
  const [prompt, setPrompt] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const send = useMutation({
    mutationFn: (p: string) => post('/api/chat', { prompt: p }),
    onSuccess: (r) => { qc.setQueryData(['/api/chat'], (old: any) => ({ ...old, messages: r.messages })); setPending(null); setErr('') },
    onError: (e: any) => { setPending(null); setErr(e.message) },
  })
  useEffect(() => { if ((d?.messages?.length || 0) > 0 || pending) end.current?.scrollIntoView({ block: 'end' }) }, [d?.messages?.length, pending])
  if (isLoading || !d) return <Skel n={3} h={80} />
  const go = (p: string) => { if (!p.trim() || send.isPending) return; setPending(p); setPrompt(''); send.mutate(p) }
  const msgs = d.messages as any[]
  return (
    <>
      <div className="ctxrow asst-row"><Mascot size={44} /><Chip kind="ai" icon="auto_awesome">AI advice, not ESPN data</Chip>{d.chips.map((c: any) => <Chip key={c.text} icon={c.icon}>{c.text}</Chip>)}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '8px 0' }}>
        <span className="fresh">Uses {d.backend !== 'api' ? 'your Claude subscription' : 'the Anthropic API'} · reads your league through tools · read-only</span>
        <button className="btn sm" onClick={async () => { await http('/api/chat', { method: 'DELETE' }); qc.setQueryData(['/api/chat'], { ...d, messages: [] }) }}><Icon n="delete_sweep" /> Clear</button>
      </div>
      {msgs.length === 0 && !pending && <><Empty title="Ask anything about your team" body="I read your roster, the waiver wire, trades and news through tools, and never invent stats." icon="forum" />
        <div className="ex">{EXAMPLES.map(([l, p]) => <button key={l} className="pill" onClick={() => go(p)}>{l}</button>)}</div></>}
      {msgs.map((m, i) => <Msg key={i} m={m} />)}
      {pending && <><div className="msg user"><div className="t">{pending}</div></div><div className="msg"><Skel n={1} h={40} /><span className="fresh">Looking at your league...</span></div></>}
      {err && <Notice kind="warn" icon="smart_toy">{err}</Notice>}
      <div ref={end} style={{ height: 70 }} />
      <div className="chatbar"><form onSubmit={(e) => { e.preventDefault(); go(prompt) }}>
        <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask about your lineup, waivers, trades, injuries..." aria-label="Ask the assistant" />
        <HeroButton icon="arrow_upward" title="Send" type="submit" size={44} disabled={send.isPending} /></form></div>
    </>
  )
}
