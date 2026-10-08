import { Link } from 'react-router-dom'
import { useApi, post, qc } from '../api'
import { Ring } from '../fx'
import { AskAI, Avatar, Chip, Empty, FAvatar, Icon, MovesBlock, NewsEvent, Notice, RecCard, Section, Skel, useActions } from '../ui'
import { Scoreboard } from '../board'
import type { FTeam, Player } from '../types'

export default function Overview() {
  const { data: d, isLoading } = useApi<any>('/api/overview')
  const { toast } = useActions()
  if (isLoading || !d) return <Skel n={4} h={90} />
  const chips = [
    d.ready ? <Chip key="r" kind="good" icon="check_circle">Lineup ready</Chip> : <Chip key="r" kind="bad" icon="error">{d.swapCount} lineup change{d.swapCount !== 1 ? 's' : ''} recommended</Chip>,
    d.nextLock && <Chip key="n" icon="lock_clock">Next lock: {d.nextLock.label} ({d.nextLock.name})</Chip>,
    d.locked > 0 && <Chip key="l" icon="lock">{d.locked} starter{d.locked !== 1 ? 's' : ''} locked</Chip>,
    d.emptySlots > 0 && <Chip key="e" kind="bad" icon="person_off">{d.emptySlots} empty lineup slot{d.emptySlots !== 1 ? 's' : ''}</Chip>,
    d.waiverRank > 0 && <Chip key="w" icon="format_list_numbered">Waiver priority #{d.waiverRank}</Chip>,
    d.faabLeft != null && <Chip key="f" icon="payments">FAAB ${d.faabLeft} left</Chip>,
  ]
  const recheck = async () => { await post('/api/refresh'); qc.invalidateQueries(); toast('Re-checked injuries and edges') }
  return (
    <>
      {d.scoreboard ? <Scoreboard s={d.scoreboard} age={d.age} ttl={d.ttl} /> : <Empty title="No matchup this week" body="Your team has a bye or the schedule hasn't loaded." icon="event_busy" />}
      <div className="ctxrow" style={{ marginTop: 14 }}>{chips}</div>

      <Section title="News that changes my lineup" aside={d.scanStatus || 'AI reads ESPN news; every item links to its source'} />
      {d.blocks.length === 0 && <Notice kind="good" icon="check_circle">Nothing in the news or injury reports changes your lineup right now.</Notice>}
      {d.blocks.map((b: any, i: number) => b.kind === 'event' ? <NewsEvent key={i} ev={b.event} /> :
        <Notice key={i} kind={b.tone} icon={b.kind === 'cascade' ? 'bolt' : 'schedule'}><b>{b.title}:</b> {b.text}</Notice>)}
      <div className="actions">
        <button className="btn sm" onClick={recheck}><Icon n="refresh" /> Re-check injuries &amp; edges</button>
        {(d.blocks.length > 0 || d.hasEvents) && <AskAI label="Summarize news with AI" prompt="Summarize the news and injuries affecting my roster this week and what I should do before lock." title="News summary" icon="newspaper" />}
      </div>

      <div className="cols">
        <div>
          <Section title="Needs your attention" aside="from your roster + the value model" />
          {d.swaps.map((s: any, i: number) => (
            <div key={i}>
              <RecCard title={`Start ${s.in.name}` + (s.out ? ` over ${s.out.name}` : '')} body={s.reason} icon="swap_vert" tone={s.gain >= 5 ? 'act' : ''} gain={s.gain} gainLabel="proj pts"
                why={`${s.in.pos} · ${s.in.team} · ${s.edgeLabel}`} edgeNote={s.fromEdge ? s.edgeNote : ''} todo={s.action} players={[s.in, ...(s.out ? [s.out] : [])]} />
              <div className="actions"><Link to="/team" className="btn sm"><Icon n="arrow_forward" /> Open My Team</Link>
                <AskAI label="Ask AI why" prompt={`Explain the lineup change: start ${s.in.name} instead of ${s.out ? s.out.name : 'the empty slot'}. Use optimize_lineup and the news.`} title="Why this lineup change" /></div>
            </div>))}
          {d.planWarnings.map((w: string, i: number) => <Notice key={i} kind="warn" icon="warning">{w}</Notice>)}
          <MovesBlock moves={d.moves} limit={1} showEmpty={false} />
          {d.swaps.length === 0 && d.planWarnings.length === 0 && d.moves.moves.length === 0 && !d.moves.streams.some((s: any) => s.swap) &&
            <Notice kind="good" icon="check_circle"><b>Nothing urgent.</b> Your lineup is set and no waiver move is clearly worth making.</Notice>}
        </div>
        <div>
          <Section title="League standing" />
          <div className="rows">{d.standings.map((t: FTeam) => (
            <div key={t.id} className="row" style={{ gridTemplateColumns: 'auto 1fr auto', background: t.me ? 'var(--hover)' : undefined }}>
              <span className="num" style={{ width: 22, fontWeight: 700, color: 'var(--ink-3)' }}>{t.standing}</span>
              <div className="who"><FAvatar t={t} size={34} /><div style={{ minWidth: 0 }}><div className="nm">{t.name}</div><div className="sub">{t.owner}</div></div></div>
              <div className="stat"><b>{t.record}</b><small>{t.pf} PF</small></div>
            </div>))}</div>
          <div className="actions" style={{ marginTop: 8 }}><Link to="/league" className="btn sm"><Icon n="leaderboard" /> Full league</Link></div>
          <Section title="Your week at a glance" />
          {d.top.length === 0 ? <Empty title="No starters set" icon="groups" /> : d.top.map((p: Player) => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0' }}><Avatar p={p} size={40} />
              <div style={{ minWidth: 0 }}><div className="nm">{p.name}</div><div className="fresh">{p.pos} · {p.opp ? `vs ${p.opp}` : 'Bye'}</div></div>
              <span style={{ marginLeft: 'auto' }}><Ring value={Math.min(p.proj / 30, 1)} size={52} label={`${p.proj.toFixed(1)} projected`}><span className="num" style={{ fontWeight: 700, fontSize: 14 }}>{p.proj.toFixed(1)}</span></Ring></span></div>))}
          <div className="actions"><AskAI label="Review my whole lineup" prompt="Review my lineup for this week: who to start and sit and why." title="Lineup review" icon="fact_check" /></div>
        </div>
      </div>
    </>
  )
}
