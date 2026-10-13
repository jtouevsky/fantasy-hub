import { Chip, FAvatar, Fresh } from './ui'
import type { FTeam } from './types'

/** Weekly matchup scoreboard: both teams and their projected (and, once games start, actual) points. */
export function Scoreboard({ s, age, ttl }: { s: any; age: number | null; ttl: number }) {
  const fav = s.myProj - s.oppProj
  const started = s.state !== 'Pregame'
  const text = fav > 0.05 ? `${s.me.name} favored by ${fav.toFixed(1)} (projection)` : fav < -0.05 ? `${s.opp.name} favored by ${(-fav).toFixed(1)} (projection)` : 'Projected dead even'
  const side = (t: FTeam, r: boolean) => (
    <div className={`side-t ${r ? 'r' : ''}`}><FAvatar t={t} size={56} /><div style={{ minWidth: 0 }}><div className="name">{t.name}</div><div className="sub">{t.owner} · {t.record} · #{t.standing}</div></div></div>
  )
  const score = (proj: number, act: number) => (
    <div className="p"><span className="legend">Projected</span><span className="big num">{proj.toFixed(1)}</span>{started && <div className="actual num">Actual {act.toFixed(1)}</div>}</div>
  )
  return (
    <section className="board" aria-label={`Week ${s.week} matchup`}>
      <div className="meta"><span>Week {s.week} · {s.state}</span><span><Fresh age={age} ttl={ttl} /></span></div>
      <div className="grid">{side(s.me, false)}<div className="pair">{score(s.myProj, s.myScore)}<span className="sep">vs</span>{score(s.oppProj, s.oppScore)}</div>{side(s.opp, true)}</div>
      <div className="foot"><Chip icon="insights">{text}</Chip><Chip icon="info">ESPN projections, not a win-probability model</Chip></div>
    </section>
  )
}
