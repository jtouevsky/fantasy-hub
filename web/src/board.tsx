import { Chip, FAvatar, Fresh } from './ui'
import { Ring, Ticker, useIllumination } from './fx'
import type { FTeam } from './types'

/** Weekly matchup scoreboard. Overview: fluid-illumination surface with a projection-share ring per side. Matchup: split-flap digits that flip only when a number changes. */
export function Scoreboard({ s, age, ttl, variant = 'ring' }: { s: any; age: number | null; ttl: number; variant?: 'ring' | 'flap' }) {
  const ill = useIllumination()
  const fav = s.myProj - s.oppProj
  const started = s.state !== 'Pregame'
  const total = Math.max(s.myProj + s.oppProj, 1)
  const text = fav > 0.05 ? `${s.me.name} favored by ${fav.toFixed(1)} (projection)` : fav < -0.05 ? `${s.opp.name} favored by ${(-fav).toFixed(1)} (projection)` : 'Projected dead even'
  const side = (t: FTeam, r: boolean) => (
    <div className={`side ${r ? 'r' : ''}`}><FAvatar t={t} size={72} /><div style={{ minWidth: 0 }}><div className="name">{t.name}</div><div className="sub">{t.owner} · {t.record} · #{t.standing}</div></div></div>
  )
  const score = (proj: number, act: number, share: number, who: string) => variant === 'flap'
    ? <div className="p"><span className="legend">Projected</span><span className="big"><Ticker value={proj.toFixed(1)} /></span>{started && <div className="actual num">Actual <Ticker value={act.toFixed(1)} /></div>}</div>
    : <div className="p"><Ring value={share} size={150} label={`${who} holds ${Math.round(share * 100)}% of the combined projection`}>
        <span><span className="legend">Projected</span><span className="big"><Ticker value={proj.toFixed(1)} /></span>{started && <div className="actual num">Actual <Ticker value={act.toFixed(1)} /></div>}</span></Ring></div>
  return (
    <section className="board" aria-label={`Week ${s.week} matchup`} ref={ill.ref as any} onPointerMove={ill.onPointerMove}>
      <div className="meta"><span>Week {s.week} · {s.state}</span><span><Fresh age={age} ttl={ttl} /></span></div>
      <div className="grid">{side(s.me, false)}<div className="pair">{score(s.myProj, s.myScore, s.myProj / total, s.me.name)}<span className="sep">–</span>{score(s.oppProj, s.oppScore, s.oppProj / total, s.opp.name)}</div>{side(s.opp, true)}</div>
      <div className="foot"><Chip kind="info" icon="insights">{text}</Chip><Chip icon="info">ESPN projections, not a win-probability model</Chip></div>
    </section>
  )
}
