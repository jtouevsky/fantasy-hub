import { useApi } from '../api'
import { AskAI, Avatar, Chip, Empty, GameEnv, NflTag, Notice, Section, Skel, StatusChip, TeamBadge } from '../ui'
import { Scoreboard } from '../board'
import type { Player } from '../types'

function Half({ p, right, win, started }: { p: Player | null; right: boolean; win: boolean; started: boolean }) {
  if (!p) return <div className={`half ${right ? 'r' : ''}`}><span className="fresh">Empty slot</span></div>
  const big = started && p.weekPts >= 20
  return (
    <div className={`half ${right ? 'r' : ''} ${win ? 'win' : ''}`} style={{ '--tc': p.color } as any}>
      <Avatar p={p} size={42} />
      <div style={{ minWidth: 0 }}><div className="nm">{p.name}</div>
        <div className="sub"><Chip kind="pos">{p.pos}</Chip><StatusChip p={p} />{big && <Chip kind="good" icon="star">Big game</Chip>}<span>{p.opp ? `vs ${p.opp}` : 'Bye'} {p.onBye ? '' : p.kick}</span></div></div>
      <div className="stat"><b>{p.proj.toFixed(1)}</b><small>{p.hasEdge ? `ESPN ${p.espnProj.toFixed(1)}` : 'proj'}</small>{started && <div className="fresh num">actual {p.weekPts.toFixed(1)}</div>}</div>
    </div>
  )
}

export default function Matchup() {
  const { data: d, isLoading } = useApi<any>('/api/matchup')
  if (isLoading || !d) return <Skel n={4} h={80} />
  if (!d.scoreboard) return <Empty title="No matchup this week" body="Your team has a bye or the schedule hasn't loaded." icon="event_busy" />
  const s = d.scoreboard
  return (
    <>
      <Scoreboard s={s} age={d.age} ttl={d.ttl} variant="flap" />
      {d.started && !d.demo && <Notice icon="sync">Scores update when you press <b>Refresh</b> (about every few minutes at most). This is not a live feed.</Notice>}
      <div className="ctxrow" style={{ marginTop: 14 }}><Chip icon="sports_football">{d.remainingA} of your starters yet to play</Chip><Chip icon="sports_football">{d.remainingB} of theirs yet to play</Chip></div>
      {d.envs.length > 0 && <><Section title="Game environment" aside="Vegas lines + forecast, as of the last refresh" />
        {d.envs.map((e: any, i: number) => <div key={i} style={{ margin: '8px 0' }}><TeamBadge abbr={e.team} size={26} /> <b>{e.team}</b> vs <TeamBadge abbr={e.opp} size={26} /> <b>{e.opp}</b> <span className="fresh">{e.kickoff}</span><GameEnv e={e} /></div>)}</>}
      <Section title="Starters head to head" aside="your side left" />
      <div className="rows">{d.duels.map((x: any, i: number) => <div key={i} className="duel"><Half p={x.a} right={false} win={x.winA} started={d.started} /><div className="mid">{x.slot}</div><Half p={x.b} right win={x.winB} started={d.started} /></div>)}</div>
      <div className="fresh" style={{ marginTop: 8 }}>Starter projections sum to {d.sumA.toFixed(1)} vs {d.sumB.toFixed(1)}; ESPN's team projections above may differ slightly. Highlighted = higher {d.started ? 'actual' : 'projected'} points at that slot.</div>
      <div className="actions"><AskAI label="Break down this matchup" prompt={`Break down my week ${s.week} matchup against ${s.opp.name}: where am I strong or weak, and what could swing it?`} title="Matchup breakdown" icon="scoreboard" /></div>
    </>
  )
}
