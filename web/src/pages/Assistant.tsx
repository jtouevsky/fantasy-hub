import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useApi, post, http, qc } from '../api'
import { Chip, Icon, Notice, Empty, Skel } from '../ui'
import { Markdown } from '../md'
import { Spinner } from '../fx'
import { Quick } from '../pick'

const CARDS: { icon: string; title: string; sub: string; prompt: string }[] = [
  { icon: 'sports_football', title: 'Who should I start?', sub: 'Lineup calls for this week, with the reason for each.', prompt: 'Who should I start this week and why?' },
  { icon: 'swap_horiz', title: 'Find me a trade', sub: 'A fair-for-you offer the other manager would plausibly accept.', prompt: 'Scan the whole league for a trade that helps my lineup, slightly in my favor (about 60/40 in my value), that the other manager would plausibly accept. Show the offer ladder.' },
  { icon: 'person_add', title: 'Any waiver moves?', sub: 'Adds, drops and streaming, or a clear "no move needed".', prompt: 'Do I need any add/drop or streaming move this week? If not, say so.' },
  { icon: 'medical_services', title: 'Injuries and byes', sub: 'Who is hurt or off this week, and what to do about it.', prompt: 'Is anyone on my team injured or on a bye, and what should I do?' },
  { icon: 'sell', title: 'Who should I sell?', sub: 'Players priced above what their usage supports.', prompt: 'Which of my players should I sell high on, and who could I realistically get back?' },
  { icon: 'insights', title: 'How is my season going?', sub: 'Standing, playoff odds and the biggest lever left.', prompt: 'Give me a short read on my season: standing, playoff odds, and the single biggest thing I can do to improve them.' },
]
const QUICK = [
  { icon: 'sports_football', text: 'Start/sit', prompt: CARDS[0].prompt }, { icon: 'swap_horiz', text: 'Find a trade', prompt: CARDS[1].prompt }, { icon: 'person_add', text: 'Waivers', prompt: CARDS[2].prompt },
  { icon: 'medical_services', text: 'Injuries', prompt: CARDS[3].prompt }, { icon: 'sell', text: 'Sell high', prompt: CARDS[4].prompt }, { icon: 'insights', text: 'My season', prompt: CARDS[5].prompt },
]

export function MoveCards({ moves }: { moves: any }) {
  const C: Record<string, [string, string]> = { high: ['good', 'verified'], medium: ['', 'help'], low: ['warn', 'warning'] }
  return (
    <>
      {moves.moves?.map((m: any, i: number) => (
        <div key={i} className="mv"><div className="h"><b>Add {m.add}{m.drop ? `, drop ${m.drop}` : ''}</b><span className="num">{m.gain_this_week >= 0 ? '+' : ''}{m.gain_this_week} this week · {m.gain_rest_of_season >= 0 ? '+' : ''}{m.gain_rest_of_season} rest of season</span></div>
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
      <div className="ctxrow"><Chip kind="ai" icon="auto_awesome">AI advice, not ESPN data</Chip>{d.chips.map((c: any) => <Chip key={c.text} icon={c.icon}>{c.text}</Chip>)}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '8px 0' }}>
        <span className="fresh">Uses {d.backend !== 'api' ? 'your Claude subscription' : 'the Anthropic API'} · reads your league through tools · read-only</span>
        <button className="btn sm" onClick={async () => { await http('/api/chat', { method: 'DELETE' }); qc.setQueryData(['/api/chat'], { ...d, messages: [] }) }}><Icon n="delete_sweep" /> Clear</button>
      </div>
      {msgs.length === 0 && !pending && <>
        <div className="hero-ai"><span className="orb shine"><Icon n="auto_awesome" /></span><h2>What do you want to know?</h2><p>Tap a card or type below. I read your roster, the waiver wire, trades and news through tools, and never invent stats.</p></div>
        <div className="prompt-grid">{CARDS.map((c) => <button key={c.title} type="button" className="pcard" onClick={() => go(c.prompt)}><Icon n={c.icon} /><b>{c.title}</b><small>{c.sub}</small></button>)}</div></>}
      {msgs.map((m, i) => <Msg key={i} m={m} />)}
      {pending && <><div className="msg user"><div className="t">{pending}</div></div><div className="msg"><Skel n={1} h={40} /><span className="fresh">Looking at your league...</span></div></>}
      {err && <Notice kind="warn" icon="smart_toy">{err}</Notice>}
      <div ref={end} style={{ height: 70 }} />
      <div className="chatbar">{msgs.length > 0 && !pending && <Quick items={QUICK} onPick={(p) => go(p)} />}<form onSubmit={(e) => { e.preventDefault(); go(prompt) }}>
        <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask anything: lineup, waivers, a trade idea, injuries..." aria-label="Ask the assistant" />
        <button className={`btn primary icon ${send.isPending ? "busy" : ""}`} type="submit" aria-label="Send" disabled={send.isPending}>{send.isPending ? <Spinner /> : <Icon n="arrow_upward" />}</button></form></div>
    </>
  )
}
