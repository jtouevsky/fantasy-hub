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
  ['min_value_edge', 'Add must beat the player he replaces by (stable ppg)', 0, 10, 0.5], ['min_touches', 'Minimum touches+targets per game for an add', 0, 20, 0.5], ['min_snap_share', 'Or minimum offensive snap share (0-1)', 0, 1, 0.05],
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
        <div className="field"><label>Lineup decisions use</label><div className="pills" title="Median is the default. Safe also weights each player's floor, Upside his ceiling, Mean is the plain projection.">{['Median', 'Safe', 'Upside', 'Mean'].map((x) => <button key={x} className={`pill ${s.risk_mode === x ? 'on' : ''}`} onClick={() => set('risk_mode', x)}>{x}</button>)}</div></div>
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

function Report() {
  const { data: d, isLoading } = useApi<any>('/api/report', { stale: 60_000 })
  if (isLoading || !d) return <Skel n={3} h={70} />
  return (
    <>
      <Notice icon="fact_check">Every add and lineup swap the app recommends is recorded. A recommendation is a <b>hit</b> when the player it said to add or start scored more fantasy points than the player he replaced, over the games played since (up to 3 weeks), under your league scoring.</Notice>
      <div className="kpis"><div className="kpi"><b>{d.rate != null ? `${d.rate}%` : '-'}</b><small>Hit rate ({d.hits} of {d.scored} scored)</small></div><div className="kpi"><b>{d.total}</b><small>Recommendations recorded</small></div><div className="kpi"><b>{d.pending}</b><small>Waiting for games</small></div></div>
      {d.weeks.length > 0 && <><Section title="By week" /><div className="card"><table className="edge-table"><thead><tr><th>Week</th><th>Scored</th><th>Hits</th><th>Hit rate</th></tr></thead><tbody>{d.weeks.map((w: any) => <tr key={w.week}><td>Week {w.week}</td><td className="num">{w.n}</td><td className="num">{w.hits}</td><td className="num">{w.rate}%</td></tr>)}</tbody></table></div></>}
      <Section title="Every recommendation" aside="newest first" />
      {d.rows.length === 0 ? <Empty title="Nothing recorded yet" body="Open Overview or Players while connected to your league and the moves shown there are recorded for scoring." icon="fact_check" /> :
        d.rows.map((r: any) => <div key={r.id} className="neg"><Chip kind={r.hit == null ? '' : r.hit ? 'good' : 'bad'} icon={r.hit == null ? 'hourglass_top' : r.hit ? 'check_circle' : 'cancel'}>{r.hit == null ? 'Waiting' : r.hit ? 'Hit' : 'Miss'}</Chip>
          <span><b>{r.kind === 'add' ? 'Add' : 'Start'} {r.add_name}</b>{r.drop_name ? ` over ${r.drop_name}` : ''} <span className="fresh">· week {r.week} · {r.confidence || 'lineup'}</span></span>
          <small>{r.hit == null ? `predicted ${r.pred_gain >= 0 ? '+' : ''}${r.pred_gain}` : `${r.add_pts} vs ${r.drop_pts} pts (${r.diff >= 0 ? '+' : ''}${r.diff})`}</small></div>)}
    </>
  )
}

export default function More({ tab, setTab }: { tab: string; setTab: (t: string) => void }) {
  const tabs = ['News', 'My strategy', 'Report card', 'Edge engine', 'Recommendation log']
  return (
    <>
      <div className="pills" role="tablist">{tabs.map((t) => <button key={t} className={`pill ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === 'News' ? <News /> : tab === 'My strategy' ? <Strategy /> : tab === 'Report card' ? <Report /> : tab === 'Edge engine' ? <Edge /> : <Log />}
    </>
  )
}
