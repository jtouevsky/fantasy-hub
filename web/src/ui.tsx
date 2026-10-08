import { createContext, memo, ReactNode, useContext, useState } from 'react'
import type { Boot, FTeam, Player } from './types'

// ---- app-wide context ------------------------------------------------------------------
export const BootCtx = createContext<Boot | null>(null)
export const useBoot = () => useContext(BootCtx) as Boot
export interface Actions { openPlayer: (id: number, origin?: HTMLElement | null) => void; askAI: (prompt: string, title: string) => void; toast: (msg: string) => void }
export const ActionsCtx = createContext<Actions>({ openPlayer: () => {}, askAI: () => {}, toast: () => {} })
export const useActions = () => useContext(ActionsCtx)

// ---- primitives ------------------------------------------------------------------------
export const Icon = ({ n, cls = '' }: { n: string; cls?: string }) => <span className={`ms ${cls}`} aria-hidden="true">{n}</span>
export const Chip = ({ children, kind = '', icon, title }: { children: ReactNode; kind?: string; icon?: string; title?: string }) => (
  <span className={`chip ${kind}`} title={title}>{icon && <Icon n={icon} />}{children}</span>
)
export const Section = ({ title, aside }: { title: string; aside?: ReactNode }) => (
  <div className="sec"><h3>{title}</h3><span className="rule" />{aside && <span className="aside">{aside}</span>}</div>
)
export const Notice = ({ children, kind = '', icon = 'info' }: { children: ReactNode; kind?: string; icon?: string }) => (
  <div className={`notice ${kind}`} role="status"><Icon n={icon} /><div>{children}</div></div>
)
export const Empty = ({ title, body, icon = 'search_off' }: { title: string; body?: string; icon?: string }) => (
  <div className="empty"><Icon n={icon} /><b>{title}</b>{body}</div>
)
export const Skel = ({ n = 3, h = 64 }: { n?: number; h?: number }) => (
  <>{Array.from({ length: n }, (_, i) => <div key={i} className="skel" style={{ height: h }} aria-hidden="true" />)}<span className="sr-only" role="status">Loading</span></>
)
export const signed = (x: number, d = 1) => (x >= 0 ? '+' : '') + x.toFixed(d)

export function Fresh({ age, ttl }: { age: number | null; ttl: number }) {
  if (age === null) return null
  const m = Math.floor(age / 60)
  const stale = age > ttl * 2
  return <span className={`fresh ${stale ? 'stale' : ''}`}><Icon n="schedule" /> {stale ? 'Stale - ' : ''}Updated {m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ago`}</span>
}

// ---- badges / avatars (images lazy-load at their displayed size; failures fall back to initials) ------------
export const TeamBadge = memo(function TeamBadge({ abbr, size = 22, ring = true }: { abbr: string; size?: number; ring?: boolean }) {
  const boot = useBoot()
  const t = boot.nfl[abbr] || boot.nfl[abbr?.toUpperCase()]
  const [bad, setBad] = useState(false)
  const style: any = { '--s': `${size}px`, '--tc': ring && t ? t.color : 'transparent' }
  if (t && !bad && t.logo) {
    style['--dx'] = `${t.dx}%`; style['--dy'] = `${t.dy}%`; style['--k'] = t.k
    return <span className="tbadge" style={style} role="img" aria-label={t.name} title={t.name}><img src={t.logo} alt="" width={size} height={size} loading="lazy" decoding="async" onError={() => setBad(true)} /></span>
  }
  return <span className="tbadge fb" style={style} role="img" aria-label={abbr}><b>{(abbr || '?').slice(0, 3)}</b></span>
})

const initials = (n: string) => { const p = n.replace(/\./g, ' ').split(/\s+/).filter(Boolean); return !p.length ? '?' : p.length === 1 ? p[0].slice(0, 2).toUpperCase() : (p[0][0] + p[p.length - 1][0]).toUpperCase() }

/** Player portrait. The initials fallback exists ONLY when there is no image or it failed to load; behind a loaded image there is just the team-color backdrop.
 *  The image fills the circle (object-fit: cover, anchored near the top so heads are never cut off); the source is picked by displayed size. */
export const Avatar = memo(function Avatar({ p, size = 44 }: { p: Pick<Player, 'name' | 'pos' | 'team' | 'color' | 'img'>; size?: number; big?: boolean }) {
  const [bad, setBad] = useState(false)
  if (p.pos === 'D/ST') return <TeamBadge abbr={p.team} size={size} />
  const src = p.img ? (size <= 46 ? p.img.s : p.img.m) : null
  const showImg = !!src && !bad
  return (
    <span className="avatar" data-fb={showImg ? undefined : ''} style={{ '--s': `${size}px`, '--tc': p.color } as any}>
      {showImg ? <img src={src!} alt="" width={size} height={size} loading={size >= 100 ? 'eager' : 'lazy'} decoding="async" onError={() => setBad(true)} /> : <span className="ini">{initials(p.name)}</span>}
    </span>
  )
})

export const FAvatar = memo(function FAvatar({ t, size = 56 }: { t: FTeam; size?: number }) {
  const [bad, setBad] = useState(false)
  const showImg = !!t.logo && !bad
  return (
    <span className="avatar flogo" data-fb={showImg ? undefined : ''} style={{ '--s': `${size}px`, '--tc': t.color } as any} role="img" aria-label={t.name} title={t.name}>
      {showImg ? <img src={t.logo!} alt="" width={size} height={size} loading="lazy" decoding="async" onError={() => setBad(true)} /> : <span className="ini">{initials(t.name)}</span>}
    </span>
  )
})

export const NflTag = ({ abbr }: { abbr: string }) => (!abbr || abbr === 'None' ? null : <span className="nflt"><TeamBadge abbr={abbr} size={18} />{abbr}</span>)

const TAG_ICON: Record<string, string> = { 'buy low': 'trending_up', 'sell high': 'trending_down', 'role growing': 'moving', 'role shrinking': 'trending_flat', 'td-dependent': 'casino', 'volume-backed': 'stacked_bar_chart' }
export const TagChips = ({ p }: { p: Player }) => (
  <>{p.tags.map(([t, why]) => {
    const st = p.st
    const label = t === 'td-dependent' && st ? `TD-dependent · ${Math.round(st.tdShare * 100)}% TDs · ${st.touches.toFixed(1)} t/g`
      : t === 'volume-backed' && st ? `Volume-backed · ${st.touches.toFixed(1)} t/g` : t
    return <Chip key={t} kind={t === 'td-dependent' ? 'warn' : t === 'volume-backed' ? 'good' : 'ai'} icon={TAG_ICON[t] || 'sell'} title={why}>{label}</Chip>
  })}</>
)

export const StatusChip = ({ p }: { p: Pick<Player, 'onBye' | 'status' | 'statusLabel' | 'out'> }) => {
  if (p.onBye) return <Chip kind="info" icon="event_busy">Bye week</Chip>
  if (!p.statusLabel) return null
  return <Chip kind={p.out ? 'bad' : p.status === 'DOUBTFUL' ? 'bad' : 'warn'} icon={p.out ? 'medical_services' : p.status === 'DOUBTFUL' ? 'warning' : 'help'}>{p.statusLabel}</Chip>
}

export function EdgeWhy({ p, open }: { p: Player; open?: boolean }) {
  if (!p.hasEdge || !p.edge?.length) return null
  return (
    <details className="why" open={open}>
      <summary><Icon n="bolt" /> ESPN {p.espnProj.toFixed(1)} → Adjusted {p.proj.toFixed(1)} <span className="fresh">why</span></summary>
      <ul>{p.edge.map((a: any, i: number) => (
        <li key={i}><b className={`num ${a.delta > 0 ? 'up' : 'dn'}`}>{signed(a.delta)}</b> {a.label}<div>{a.reason}</div>
          <small>Source: {a.source} · {a.confidence} confidence · {a.at}{Math.abs(a.raw - a.delta) >= 0.05 ? ` · capped from ${signed(a.raw)}` : ''}</small></li>))}
      </ul>
      <small>Adjustments are added to ESPN's projection and capped per player. Missing data means no adjustment.</small>
    </details>
  )
}

export function EdgeContext({ p }: { p: Player }) {
  if (!p.context?.length) return null
  return (
    <details className="why">
      <summary><Icon n="info" /> Opportunity context <span className="fresh">not in projection</span></summary>
      <ul>{p.context.map((c: any, i: number) => <li key={i}><b className={`num ${c.pts > 0 ? 'up' : 'dn'}`}>{signed(c.pts)}</b> {c.label} (context)<div>{c.text}</div><small>Source: {c.source} · {c.confidence} confidence</small></li>)}</ul>
      <small>Shown for information. In the backtest this estimate did not improve weekly accuracy over recent form, so it does not move the projection.</small>
    </details>
  )
}

// ---- rows ------------------------------------------------------------------------------
export const PlayerRow = memo(function PlayerRow({ p, slot, moved, note, showActual = true, valuePct, valueLabel, whyOpen = true }:
  { p: Player; slot?: string; moved?: boolean; note?: string; showActual?: boolean; valuePct?: number; valueLabel?: string; whyOpen?: boolean }) {
  const { openPlayer } = useActions()
  const cls = ['row', p.out || p.onBye ? 'out' : p.risky ? 'risk' : '', moved ? 'moved' : ''].join(' ')
  return (
    <div className={cls} role="listitem" style={{ '--tc': p.color } as any}>
      <div className="who">
        {slot && <span className="slot">{slot}</span>}
        <button className="av-btn" aria-label={`Open ${p.name}`} onClick={(e) => openPlayer(p.id, e.currentTarget.querySelector('.avatar') as HTMLElement)}><Avatar p={p} size={44} /></button>
        <div style={{ minWidth: 0 }}>
          <div className="nm">{p.name}</div>
          <div className="sub"><Chip kind="pos">{p.pos}</Chip><NflTag abbr={p.team} /><StatusChip p={p} />
            {p.lock === 'locked' && <Chip icon="lock">Locked</Chip>}
            {p.hasEdge && !p.onBye && <Chip kind="ai" icon="bolt">Edge {signed(p.edgeTotal)}</Chip>}<TagChips p={p} />{p.watch && <Chip icon="star">Watching</Chip>}{note}</div>
          {whyOpen && <><EdgeWhy p={p} /><EdgeContext p={p} /></>}
        </div>
      </div>
      <div className="opp">{p.opp ? `vs ${p.opp}` : p.onBye ? 'Bye' : ''}<small>{p.onBye ? '' : p.kick}</small></div>
      <div className="stat"><b>{p.onBye ? '-' : p.proj.toFixed(1)}</b><small>{p.hasEdge && !p.onBye ? `ESPN ${p.espnProj.toFixed(1)}` : 'Proj'}</small></div>
      {showActual
        ? <div className="stat hide-sm"><b>{p.weekPts.toFixed(1)}</b><small>Actual</small></div>
        : <div className="stat hide-sm"><b>{valueLabel ?? p.actualPpg.toFixed(1)}</b><small>{valueLabel ? 'ROS pts' : 'Avg'}</small>{valuePct !== undefined && <div className="bar"><i style={{ width: `${Math.max(2, Math.min(100, valuePct))}%` }} /></div>}</div>}
      <button className="iconbtn" aria-label={`Details for ${p.name}`} onClick={(e) => openPlayer(p.id, (e.currentTarget.closest('.row')?.querySelector('.avatar') as HTMLElement) || null)}><Icon n="chevron_right" /></button>
    </div>
  )
})

export const Rows = ({ children, label }: { children: ReactNode; label?: string }) => <div className="rows" role="list" aria-label={label}>{children}</div>

// ---- cards -----------------------------------------------------------------------------
export function RecCard({ title, body, icon = 'bolt', tone, gain, gainLabel, why, todo, players = [], edgeNote }:
  { title: string; body: ReactNode; icon?: string; tone?: string; gain?: number; gainLabel?: string; why?: string; todo?: string; players?: Player[]; edgeNote?: string }) {
  return (
    <article className="rec">
      <div className={`ic ${tone || ''}`}><Icon n={icon} /></div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <h4>{title}</h4><p>{body}</p>{why && <div className="why">{why}</div>}
        {edgeNote && <div className="edgenote"><Icon n="bolt" /><span>{edgeNote}</span></div>}
        {todo && <div className="todo"><Icon n="arrow_forward" /><span>{todo}</span></div>}
      </div>
      {players.length > 0 && <div className="faces">{players.slice(0, 3).map((p) => <Avatar key={p.id} p={p} size={34} />)}</div>}
      {gain !== undefined && <div className="gain"><b>{signed(gain)}</b><small>{gainLabel}</small></div>}
    </article>
  )
}

const CONF: Record<string, [string, string]> = { high: ['good', 'verified'], medium: ['', 'help'], low: ['warn', 'warning'] }

export function MoveCard({ m, ask = true }: { m: any; ask?: boolean }) {
  const { askAI } = useActions()
  const title = `Add ${m.add}` + (m.drop ? `, drop ${m.drop}` : '')
  const first = m.reason.split('; ')[0].replace(/\.$/, '') + '.'
  const [k, ic] = CONF[m.confidence]
  return (
    <>
      <RecCard title={title} body={first} icon="person_add" gain={m.gain_this_week} gainLabel="this week" why={`${m.position} · ${m.addP.team} · rest of season ${signed(m.gain_rest_of_season)} pts`} players={[m.addP, ...(m.dropP ? [m.dropP] : [])]} />
      <div className="ctxrow" style={{ margin: '-2px 0 4px' }}>
        <Chip kind={k} icon={ic}>{m.confidence[0].toUpperCase() + m.confidence.slice(1)} confidence</Chip>
        {m.flags.includes('speculative') && <Chip kind="warn" icon="bolt">Speculative</Chip>}{m.flags.includes('streamer') && <Chip icon="autorenew">Streamer</Chip>}
      </div>
      <details className="exp"><summary>Why</summary><div>{m.reason}<Evidence ev={m.evidence} /><div className="fresh">{m.action}</div>
        {ask && <div className="actions"><button className="btn sm" onClick={() => askAI(`Check this move with evaluate_move: add ${m.add}${m.drop ? `, drop ${m.drop}` : ''}.`, 'Waiver move review')}><Icon n="auto_awesome" /> Ask AI about this</button></div>}</div></details>
    </>
  )
}

export function Evidence({ ev }: { ev: any }) {
  if (!ev || !ev.opportunity) return null
  const o = ev.opportunity, v = ev.value || {}, d = ev.distribution
  const f = (x: number | null | undefined, k = 1) => (x == null ? 'n/a' : x.toFixed(k))
  return (
    <div className="evid">
      <div className="evg">
        <div><b>{f(v.add_stable_ppg)}</b><small>stable ppg{v.add_raw_ppg ? ` (raw ${f(v.add_raw_ppg)})` : ''}</small></div>
        <div><b>{f(o.touches_pg)}</b><small>touches+targets / game</small></div>
        <div><b>{o.snap_pct != null ? Math.round(o.snap_pct * 100) + '%' : 'n/a'}</b><small>offensive snaps</small></div>
        <div><b>{o.td_share != null ? Math.round(o.td_share * 100) + '%' : 'n/a'}</b><small>of points from TDs</small></div>
        {d && <div><b>{d.floor} / {d.median} / {d.ceiling}</b><small>floor / median / ceiling</small></div>}
      </div>
      {v.vs && <div className="fresh">vs {v.vs}: {f(v.vs_stable_ppg)} stable ppg{v.edge != null ? ` (edge ${v.edge >= 0 ? '+' : ''}${f(v.edge)})` : ''}</div>}
      {o.td_act_pg != null && <div className="fresh">TDs per game: {f(o.td_act_pg, 2)} actual vs {f(o.td_exp_pg, 2)} expected from his opportunities{o.rz_touch_pg != null ? ` · red-zone touches/game ${f(o.rz_touch_pg)}` : ''}</div>}
      <ul>{(ev.rules || []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
      {ev.news_reason && <div className="fresh">Sourced reason: {ev.news_reason}</div>}
    </div>
  )
}

export function StreamCard({ s }: { s: any }) {
  if (s.swap && s.bestP) {
    return <RecCard title={`Stream ${s.position}: add ${s.best}${s.current ? `, drop ${s.current}` : ''}`} body={s.reason} icon="autorenew" gain={s.this_week_gain} gainLabel="this week" why={s.plan_ahead} players={[s.bestP]} />
  }
  return <Notice kind="good" icon="check_circle"><b>{s.reason}</b> {s.plan_ahead}</Notice>
}

export function MovesBlock({ moves, showStreams = true, limit = 99, showEmpty = true }: { moves: any; showStreams?: boolean; limit?: number; showEmpty?: boolean }) {
  return (
    <>
      {showStreams && moves.streams.map((s: any) => <StreamCard key={s.position} s={s} />)}
      {moves.moves.slice(0, limit).map((m: any) => <MoveCard key={m.add_id} m={m} />)}
      {moves.empty && showEmpty && <Notice kind="good" icon="check_circle"><b>No move needed.</b> {moves.reason}</Notice>}
    </>
  )
}

export function AskAI({ label, prompt, title, icon = 'auto_awesome' }: { label: string; prompt: string; title: string; icon?: string }) {
  const { askAI } = useActions()
  return <button className="btn sm" onClick={() => askAI(prompt, title)} title="Opens an AI review. It only reads your league and never makes changes."><Icon n={icon} /> {label}</button>
}

export function Modal({ onClose, title, children }: { onClose: () => void; title: string; children: ReactNode }) {
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal"><div className="head"><b>{title}</b><button className="iconbtn" onClick={onClose} aria-label="Close"><Icon n="close" /></button></div>{children}</div>
    </div>
  )
}

export function GameEnv({ e }: { e: any }) {
  if (!e) return <Notice icon="sports_football">No game-environment data for this team this week.</Notice>
  return (
    <div>
      <div className="ctxrow">
        {e.total != null ? <><Chip icon="attach_money">{e.fav}</Chip><Chip icon="functions">Total {e.total.toFixed(1)}</Chip><Chip icon="scoreboard">{e.team} implied {e.implied.toFixed(1)}</Chip></> : <Chip icon="attach_money">No Vegas line available</Chip>}
        {e.windMph != null ? <><Chip kind={e.windMph >= 15 ? 'warn' : ''} icon="air">Wind {Math.round(e.windMph)} mph</Chip><Chip kind={e.tempF <= 25 ? 'warn' : ''} icon="thermostat">{Math.round(e.tempF)}°F</Chip>{e.precip ? <Chip icon="rainy">{Math.round(e.precip)}% precip</Chip> : null}</> : <Chip icon="partly_cloudy_day">{e.weatherNote || 'Weather n/a'}</Chip>}
      </div>
      <small className="fresh">Lines: {e.linesSource}{e.forecastAt ? ` · forecast ${e.forecastAt}` : ''}</small>
    </div>
  )
}

export function NewsEvent({ ev }: { ev: any }) {
  const st: Record<string, [string, string]> = { out: ['Out', 'bad'], ir: ['IR', 'bad'], suspended: ['Suspended', 'bad'], doubtful: ['Doubtful', 'bad'], questionable: ['Questionable', 'warn'], active: ['Cleared', 'good'] }
  const s = ev.status ? st[ev.status] : undefined
  return (
    <div className="news">
      <div className="ctxrow"><Chip kind="ai" icon="auto_awesome">AI-extracted from ESPN news</Chip>{s ? <Chip kind={s[1]} icon="medical_services">{s[0]}</Chip> : <Chip icon="newspaper">{ev.type.replace(/_/g, ' ')}</Chip>}{ev.games ? <Chip icon="event_busy">{ev.games} games</Chip> : null}<b>{ev.player}</b></div>
      <p>{ev.summary}</p>{ev.beneficiaries?.length ? <div className="fresh">Named as picking up work: {ev.beneficiaries.join(', ')}</div> : null}
      <details><summary className="fresh">Original text</summary><p>{ev.raw}</p></details>
      <small>{ev.at} UTC{ev.url && <> · <a href={ev.url} target="_blank" rel="noopener noreferrer">source</a></>}</small>
    </div>
  )
}
