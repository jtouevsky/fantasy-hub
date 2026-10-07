import { useState } from 'react'
import { useApi, put, qc } from '../api'
import { AskAI, Chip, Empty, GameEnv, Icon, NewsEvent, Notice, Section, Skel, PlayerRow, useActions, useBoot } from '../ui'

function News() {
  const { data: d, isLoading } = useApi<any>('/api/news', { stale: 10 * 60_000 })
  if (isLoading || !d) return <><Skel n={4} h={54} /><div className="fresh">Reading ESPN and Sleeper news for both rosters...</div></>
  if (!d.available) return <Empty title="News isn't available in demo mode" body="Connect your league to see ESPN and Sleeper news." icon="newspaper" />
  return (
    <>
      <Section title="Lineup alerts" aside="things that should change this week's lineup" />
      {d.alerts.length === 0 && <Notice kind="good" icon="check_circle">Nothing in the news should change your lineup this week.</Notice>}
      {d.alerts.map((a: any, i: number) => <Notice key={i} kind={{ ACT: 'bad', WATCH: 'warn', INFO: '' }[a.sev as string] || ''} icon={{ ACT: 'error', WATCH: 'visibility', INFO: 'info' }[a.sev as string] || 'info'}><b>{a.sev[0] + a.sev.slice(1).toLowerCase()}</b> · {a.who && `${a.who}: `}{a.msg}{a.action && <div className="fresh">{a.action}</div>}</Notice>)}
      <div className="actions"><AskAI label="Summarize with AI" prompt="Summarize news and injuries affecting my roster and my opponent's roster, and what it means for my lineup." title="News summary" icon="newspaper" /></div>
      {d.groups.map((g: any) => <div key={g.label}><Section title={g.label} />{g.items.map((it: any) => (
        <details key={it.p.id} className="news"><summary><b>{it.p.name}</b> · {it.p.pos} · {it.p.team}{it.p.statusLabel ? ` · ${it.p.statusLabel}` : ''}</summary>
          {it.injury && <Notice kind="warn" icon="medical_services">Sleeper: {it.injury}</Notice>}
          {it.items.map((n: any, i: number) => <div key={i} className="news"><b>{n.headline}</b><p>{n.story}</p><small>{n.source} · {n.published}</small></div>)}</details>))}</div>)}
    </>
  )
}

const FIELDS: [string, string, number, number, number][] = [
  ['stream_swap_gain', 'Swap only if it gains at least (pts)', 0, 10, 0.5], ['max_qb', 'Max QBs', 1, 4, 1], ['max_te_extra', 'Extra TEs beyond starters', 0, 3, 1], ['max_dst', 'Max D/ST', 1, 3, 1],
  ['recent_days', "Don't churn players added in the last (days)", 0, 21, 1], ['min_gain_week', 'Minimum gain this week (pts)', 0, 10, 0.5], ['min_gain_ros', '...or minimum rest-of-season gain (pts)', 0, 40, 1],
  ['speculative_extra_gain', 'Extra gain needed for one-week spikes (pts)', 0, 10, 0.5], ['playoff_weight', 'Playoff week weight', 1, 3, 0.1],
]

function Strategy() {
  const { data: d, isLoading } = useApi<any>('/api/strategy', { stale: 0 })
  const { toast } = useActions()
  const [form, setForm] = useState<any>(null)
  if (isLoading || !d) return <Skel n={3} h={80} />
  const s = form ?? d.strategy
  const set = (k: string, v: any) => setForm({ ...s, [k]: v })
  const save = async () => { await put('/api/strategy', s); qc.invalidateQueries(); setForm(null); toast('Strategy saved. Recommendations now follow it.') }
  return (
    <>
      <Notice icon="tune">These rules apply to <b>every</b> recommendation: the Players page, Overview cards, the player sheet and the AI assistant all use them. Nothing here changes anything on ESPN.</Notice>
      <Section title="Streaming" aside="pick the best option every week, ranked on THIS week only" />
      <div className="form"><label className="toggle"><input type="checkbox" checked={s.stream_dst} onChange={(e) => set('stream_dst', e.target.checked)} /> Stream D/ST</label>
        <label className="toggle"><input type="checkbox" checked={s.stream_k} disabled={!d.hasK} onChange={(e) => set('stream_k', e.target.checked)} /> Stream K {!d.hasK && <span className="fresh">(no kicker slot)</span>}</label></div>
      <Section title="Roster caps, protection and thresholds" />
      <div className="form">{FIELDS.map(([k, label, min, max, step]) => <div className="field" key={k}><label htmlFor={k}>{label}</label><input id={k} type="number" min={min} max={max} step={step} value={s[k]} onChange={(e) => set(k, Number(e.target.value))} /></div>)}
        <div className="field"><label>Explanations</label><div className="pills">{['Short', 'Beginner'].map((x) => <button key={x} className={`pill ${s.explanation === x ? 'on' : ''}`} onClick={() => set('explanation', x)}>{x}</button>)}</div></div></div>
      <div className="actions"><button className="btn primary" onClick={save}><Icon n="save" /> Save strategy</button></div>
      <div className="ctxrow"><Chip icon="grid_view">Slots: {Object.entries(d.slots).map(([k, n]) => `${n}x ${k}`).join(', ')}</Chip><Chip icon="lock">Caps: {Object.entries(d.caps).map(([k, n]) => `${k} ${n}`).join(', ')}</Chip><Chip icon="autorenew">Streaming: {d.streaming.join(', ') || 'none'}</Chip></div>
    </>
  )
}

function Edge() {
  const { data: e, isLoading } = useApi<any>('/api/edge')
  const boot = useBoot()
  if (isLoading || !e) return <Skel n={3} h={80} />
  if (!e.on) return <Empty title="The edge engine isn't running" body="Demo data has no real player IDs; with a real league it runs automatically. If this is your league, check the warnings at the top of the page." icon="bolt" />
  const names: Record<string, string> = { vegas: 'Game environment (Vegas)', weather: 'Weather', cascade: 'Injury cascade', defense: 'Opposing defense / own OL injuries', regression: 'Opportunity vs. production' }
  return (
    <>
      <Section title="How it works" />
      <Notice icon="bolt">Every number starts with <b>ESPN's projection</b>. Edges add or subtract points for specific, explainable reasons; each adjustment is stored with its source and confidence, total movement is capped per player, and if data is missing nothing is adjusted. Strengths below come from a backtest on 2024-2025 (see docs/backtest.md).</Notice>
      {e.summary && <div className="kpis"><div className="kpi"><b>{e.summary.mae_base.toFixed(2)} → {e.summary.mae_adj.toFixed(2)}</b><small>Typical weekly miss (pts), 2025 hold-out</small></div><div className="kpi"><b>{e.summary.gain_lo >= 0 ? '+' : ''}{e.summary.gain_lo.toFixed(2)} to {e.summary.gain_hi >= 0 ? '+' : ''}{e.summary.gain_hi.toFixed(2)}</b><small>95% CI of the improvement</small></div></div>}
      <Section title="Modules" />
      <div className="card"><table className="edge-table"><thead><tr><th>Module</th><th>Backtest verdict</th><th>Strength</th><th>Live haircut</th></tr></thead><tbody>
        {e.modules.map((m: any) => <tr key={m.key}><td>{names[m.key] || m.key}</td><td><Chip kind={m.decision === 'ON' ? 'good' : m.decision === 'SHRUNK' ? 'warn' : ''}>{m.decision}</Chip></td><td className="num">{m.alpha}</td><td className="num">x{e.live[m.key] ?? 1}</td></tr>)}</tbody></table></div>
      <Section title="Data sources right now" />{e.status.map((s: any) => <Notice key={s.k} icon="database"><b>{s.k}:</b> {s.v}</Notice>)}
      {e.scan && <Notice icon="auto_awesome"><b>AI news scan:</b> {e.scan}</Notice>}
      <Section title="Injury cascades in effect" aside="who is out, and who picks up the work" />
      {e.cascades.length ? e.cascades.map((c: any) => <div key={c.team} className="news"><b>{c.team}</b> · {c.absent}{c.lines.map((l: string, i: number) => <p key={i}>{l}</p>)}</div>) : <Notice kind="good" icon="check_circle">No skill-position absences are creating cascades this week.</Notice>}
      <Section title="Biggest adjustments this week" />
      {e.adjustments.length ? <div className="card"><table className="edge-table"><thead><tr><th>Player</th><th>Projection</th><th>Biggest reason</th></tr></thead><tbody>{e.adjustments.map((a: any) => <tr key={a.p.id}><td><b>{a.p.name}</b><br /><small>{a.p.pos} · {a.p.team}</small></td><td className="num">{a.label}</td><td>{a.reason}</td></tr>)}</tbody></table></div> : <Notice>No adjustments this week.</Notice>}
      <Section title="Game environments" />{e.envs.map((x: any, i: number) => <div key={i} style={{ margin: '8px 0' }}><b>{x.team} vs {x.opp}</b> <span className="fresh">{x.kickoff}</span><GameEnv e={x} /></div>)}
      {e.eventCount > 0 && <><Section title="AI-parsed news this week" aside={`${e.eventCount} events`} />{e.events.map((ev: any, i: number) => <NewsEvent key={i} ev={ev} />)}</>}
    </>
  )
}

function Log() {
  const { data: d, isLoading } = useApi<any>('/api/log', { stale: 0 })
  const [id, setId] = useState(''), [out, setOut] = useState('')
  if (isLoading || !d) return <Skel n={3} h={60} />
  if (!d.rows.length) return <Empty title="No recommendations saved yet" body="Advice from the AI, and trades you save, will collect here so you can check later whether they worked." icon="bookmark" />
  return (
    <>
      <Section title="Recommendation log" aside="mark outcomes to learn what works" />
      {d.rows.map((r: any) => <div key={r.id} className="news"><div className="ctxrow"><Chip kind="pos">{r.kind}</Chip><Chip kind={r.source === 'agent' ? 'ai' : ''}>{r.source.toUpperCase()}</Chip>{r.outcome && <Chip kind="good" icon="flag">{r.outcome}</Chip>}<span className="fresh">#{r.id} · Week {r.week || '-'} · {r.when}</span></div><p>{r.summary}</p></div>)}
      <div className="form"><div className="field"><label>Entry ID</label><input type="number" value={id || d.rows[0].id} onChange={(e) => setId(e.target.value)} /></div><div className="field"><label>Outcome</label><input type="text" value={out} onChange={(e) => setOut(e.target.value)} placeholder="Worked: won by 12 · Didn't work: he got hurt · Ignored" /></div>
        <button className="btn" disabled={!out} onClick={async () => { await put(`/api/log/${id || d.rows[0].id}`, { outcome: out }); setOut(''); qc.invalidateQueries({ queryKey: ['/api/log'] }) }}>Save outcome</button></div>
    </>
  )
}

export default function More({ tab, setTab }: { tab: string; setTab: (t: string) => void }) {
  const tabs = ['News', 'My strategy', 'Edge engine', 'Recommendation log']
  return (
    <>
      <div className="pills" role="tablist">{tabs.map((t) => <button key={t} className={`pill ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === 'News' ? <News /> : tab === 'My strategy' ? <Strategy /> : tab === 'Edge engine' ? <Edge /> : <Log />}
    </>
  )
}
