import { useApi, post, qc } from './api'
import { Avatar, Chip, EdgeContext, EdgeWhy, GameEnv, Icon, Modal, MoveCard, NewsEvent, Notice, Section, Skel, StatusChip, TagChips, TeamBadge, useActions, useBoot } from './ui'
import { Link } from 'react-router-dom'

function Trend({ h, color }: { h: any; color: string }) {
  if (!h.history?.length) return <Notice kind="warn" icon="cloud_off">Game history couldn't be loaded from ESPN right now.</Notice>
  const pts: number[] = h.history.map((x: any) => x.points)
  const max = Math.max(...pts, h.proj, 10)
  const step = max <= 40 ? 10 : 20
  const top = (Math.floor(max / step) + 1) * step
  const grid = []
  for (let g = 0; g <= top; g += step) grid.push(g)
  return (
    <div className="chart" role="img" aria-label={`Weekly fantasy points, ${pts.length} games, latest ${pts[pts.length - 1]}`}>
      {grid.map((g) => <i key={g} className="gl" style={{ bottom: `${(100 * g) / top}%` }}><b className="num">{g}</b></i>)}
      {h.history.map((x: any, i: number) => <div key={i} className="b" title={`${x.season} week ${x.week}: ${x.points}`} style={{ height: `${Math.max(1, (100 * x.points) / top)}%`, background: color }}><span>{x.week}</span></div>)}
      {h.proj > 0 && <div className="b cur" title={`Projection ${h.proj}`} style={{ height: `${(100 * h.proj) / top}%`, background: color }}><span>P</span></div>}
    </div>
  )
}

export default function PlayerSheet({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: p, isLoading, error } = useApi<any>(`/api/player/${id}`, { stale: 60_000 })
  const hist = useApi<any>(`/api/player/${id}/history`, { stale: 10 * 60_000 })
  const news = useApi<any>(`/api/player/${id}/news`, { stale: 10 * 60_000 })
  const { toast, askAI } = useActions()
  const boot = useBoot()
  const toggle = async () => { const r = await post(`/api/watch/${id}`); qc.invalidateQueries({ queryKey: [`/api/player/${id}`] }); toast(r.watching ? 'Added to your watchlist' : 'Removed from your watchlist') }
  return (
    <Modal onClose={onClose} title="Player">
      {error ? <Notice kind="warn" icon="person_off">{(error as Error).message}</Notice> : isLoading || !p ? <Skel n={3} h={90} /> : (
        <>
          <div className="hero-player" style={{ '--tc': p.color } as any}>
            <Avatar p={p} size={120} big />
            <div style={{ minWidth: 0 }}><h2>{p.name}</h2>
              <div className="ctxrow" style={{ marginTop: 10 }}><Chip kind="pos">{p.pos}</Chip><StatusChip p={p} />
                {p.ownerTeam?.me ? <Chip kind="good" icon="shield">On your team</Chip> : p.ownerTeam ? <Chip icon="groups">On {p.ownerTeam.name}</Chip> : <Chip kind="info" icon="person_add">Free agent{p.owned >= 0 ? ` · ${Math.round(p.owned)}% owned` : ''}</Chip>}
                {p.watch && <Chip icon="star">Watching</Chip>}<TagChips p={p} /></div>
              <div className="tbanner" style={{ marginTop: 10 }}><TeamBadge abbr={p.team} size={46} /><div><b>{p.nflName}</b><small>{p.team}</small></div></div></div>
          </div>
          <div className="kv">
            <div><b>{p.onBye ? '-' : p.proj.toFixed(1)}</b><small>Week {p.week} {p.hasEdge ? `ESPN ${p.espnProj.toFixed(1)} → adjusted` : 'projection'}</small></div>
            <div><b>{p.ppg.toFixed(1)}</b><small>Points / game (blended)</small></div>
            <div><b>{p.totalPts.toFixed(1)}</b><small>Season points · {p.gp} G</small></div>
            <div><b>{p.ros}</b><small>Expected points, rest of season</small></div></div>
          {p.tl && <Notice kind="warn" icon="personal_injury">{p.tl}</Notice>}
          <div className="actions"><button className="btn sm" onClick={toggle}><Icon n="star" /> {p.watch ? 'Stop watching' : 'Watch'}</button>
            <button className="btn sm" onClick={() => { askAI(`Tell me about ${p.name}: usage, outlook, and whether I should add, start, trade for or drop him. Use the tools.`, p.name); }}><Icon n="auto_awesome" /> Ask AI</button></div>

          {p.st && <>
            <Section title="Stability" aside="touchdowns regressed toward what his opportunities predict" />
            <div className="kv">
              <div><b>{p.st.ppg.toFixed(1)}</b><small>Stable points / game{p.st.raw !== p.st.ppg ? ` (raw ${p.st.raw.toFixed(1)})` : ''}</small><span className="hint">last {p.st.g} games, your scoring</span></div>
              <div><b>{Math.round(p.st.tdShare * 100)}%</b><small>of his points from TDs</small><span className="hint">{p.st.volPg?.toFixed(1)} volume + {p.st.tdPg?.toFixed(1)} TD pts/game</span></div>
              <div><b>{p.st.tdAct?.toFixed(2)} vs {p.st.tdExp?.toFixed(2)}</b><small>TDs per game: actual vs expected</small><span className="hint">expected = what his targets and carries usually produce</span></div>
              <div><b>{p.st.fmc[0]} / {p.st.fmc[1]} / {p.st.fmc[2]}</b><small>This week: floor / median / ceiling</small><span className="hint">20th / 50th / 80th percentile outcome</span></div>
            </div>
            <div className="dist" aria-hidden="true"><span>{p.st.fmc[0]}</span><div className="rail"><i style={{ left: `${(100 * p.st.fmc[0]) / (p.st.fmc[2] * 1.15)}%`, right: `${100 - (100 * p.st.fmc[2]) / (p.st.fmc[2] * 1.15)}%` }} /><u style={{ left: `${(100 * p.st.fmc[1]) / (p.st.fmc[2] * 1.15)}%` }} /></div><span>{p.st.fmc[2]}</span></div>
            {p.st.dep && <Notice kind="warn" icon="casino"><b>TD-dependent.</b> A big share of his points come from touchdowns on few touches. If he doesn't score, he tanks; the model counts him at {p.st.ppg.toFixed(1)} ppg, not {p.st.raw.toFixed(1)}.</Notice>}
            {p.st.vol && <Notice kind="good" icon="stacked_bar_chart"><b>Volume-backed.</b> His production is built on touches and targets, so it is steadier week to week.</Notice>}
          </>}
          {p.usage.length > 0 && <><Section title="Usage & opportunity" aside="this season, from play-by-play data" /><div className="kv">{p.usage.map((u: any) => <div key={u.label}><b>{u.value}</b><small>{u.label}</small><span className="hint">{u.hint}</span></div>)}
            <div><b>n/a</b><small>Route participation</small><span className="hint">not in free NFL data; use snap and target share</span></div></div></>}
          {p.context?.length > 0 && <><Section title="Opportunity context" aside="information only" /><EdgeContext p={p} /></>}
          {(p.hasEdge || p.tags.length > 0) ? <><Section title="Edge vs ESPN" aside="adjustments on top of ESPN's projection" />
            {p.hasEdge ? <EdgeWhy p={p} open /> : <Notice icon="info">No projection adjustment this week for him (no data, or nothing cleared the noise threshold).</Notice>}
            {p.tags.map(([t, txt]: any) => <div key={t} className="notice"><Chip kind="ai">{t}</Chip><div>{txt}</div></div>)}
            {p.edgeRos ? <div className="fresh"><Icon n="calendar_month" /> Rest-of-season edge: {p.edgeRos >= 0 ? '+' : ''}{p.edgeRos.toFixed(1)} pts/game (feeds trade and waiver value).</div> : null}</>
            : p.edgeChecked && <Notice icon="info">No edge data for this player this week - ESPN's projection is used as is.</Notice>}
          {p.env && <><Section title="Game environment" /><GameEnv e={p.env} /></>}

          <Section title="What you could do" />
          {p.todo.mode === 'mine' && (p.todo.onIR ? <Notice icon="personal_injury">On injured reserve; he can't be started until he returns.</Notice> : p.todo.compare.length ? (
            <table className="cmp"><thead><tr><th>Slot / current starter</th><th>Theirs</th><th>{p.name.split(' ').slice(-1)[0]}</th><th>Change</th></tr></thead><tbody>{p.todo.compare.map((c: any, i: number) => <tr key={i}><td>{c.slot}: {c.name}</td><td>{c.theirs}</td><td>{c.mine}</td><td className={c.mine > c.theirs ? 'best' : ''}>{(c.mine - c.theirs >= 0 ? '+' : '') + (c.mine - c.theirs).toFixed(1)}</td></tr>)}</tbody></table>
          ) : p.todo.starting ? <Notice kind="good" icon="check_circle">He's in your starting lineup.</Notice> : null)}
          {p.todo.mode === 'fa' && (p.todo.move ? <MoveCard m={p.todo.move} ask={false} /> : <Notice icon="info">{p.todo.why}</Notice>)}
          {p.todo.mode === 'other' && <><Notice icon="swap_horiz">He's on {p.ownerTeam.name} ({p.ownerTeam.owner}). A trade is the way to get him.</Notice><Link className="btn sm" to="/trades" onClick={onClose}><Icon n="swap_horiz" /> Explore a trade</Link></>}

          <Section title="Latest news" />
          {p.events.map((ev: any, i: number) => <NewsEvent key={i} ev={ev} />)}
          {news.isLoading ? <Skel n={1} h={50} /> : !news.data?.available ? <Notice icon="newspaper">News isn't available in demo mode.</Notice> : <>
            {news.data.injury && <Notice kind="warn" icon="medical_services"><b>Sleeper injury:</b> {news.data.injury}{news.data.injuryNotes ? ` - ${news.data.injuryNotes}` : ''}</Notice>}
            {!news.data.items.length && <Notice icon="newspaper">No recent news from ESPN.</Notice>}
            {news.data.items.map((n: any, i: number) => <div key={i} className="news"><b>{n.headline}</b><p>{n.story}</p><small>{n.source} · {n.published}</small></div>)}</>}

          <Section title="Fantasy points by game" aside="your league's scoring" />
          {hist.isLoading ? <Skel n={1} h={190} /> : hist.data ? <>{hist.data.demo && <Notice kind="warn" icon="science">Demo data: this history is made up.</Notice>}<Trend h={hist.data} color={p.color} /><div className="fresh">Scoring: {p.scoring}</div></> : null}
          <div className="fresh"><Icon n="event" /> Week {p.week}: {p.weekLabel}{p.bye ? ` · bye is week ${p.bye}` : ''}</div>
        </>)}
    </Modal>
  )
}
