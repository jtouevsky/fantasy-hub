import { useApi } from '../api'
import { Chip, Empty, FAvatar, Section, Skel } from '../ui'

export default function League() {
  const { data: d, isLoading } = useApi<any>('/api/league')
  if (isLoading || !d) return <Skel n={6} h={60} />
  return (
    <>
      <Section title="Standings" aside={`${d.count} teams · ${d.regWeeks}-game regular season`} />
      <div className="rows" role="list">{d.standings.map((t: any) => (
        <div key={t.id} className="row" style={{ gridTemplateColumns: '28px minmax(0,1fr) 80px 70px 80px', background: t.me ? 'var(--hover)' : undefined }}>
          <span className="num" style={{ fontWeight: 700, color: 'var(--ink-3)' }}>{t.standing}</span>
          <div className="who"><FAvatar t={t} size={40} /><div style={{ minWidth: 0 }}><div className="nm">{t.name} {t.me && <Chip kind="info">You</Chip>}</div><div className="sub">{t.owner}</div></div></div>
          <div className="stat"><b>{t.record}</b><small>Record</small></div><div className="stat hide-sm"><b>{t.pf}</b><small>PF</small></div>
          <div className="stat hide-sm">{t.playoffPct ? <><b>{Math.round(t.playoffPct)}%</b><small>Playoffs</small></> : null}</div>
        </div>))}</div>
      <Section title={`Week ${d.week} matchups`} aside="ESPN projections" />
      {d.matchups.length ? <div className="rows">{d.matchups.map((m: any, i: number) => (
        <div key={i} className="duel"><div className="half"><FAvatar t={m.a} size={38} /><div style={{ minWidth: 0 }}><div className="nm">{m.a.name}</div><div className="fresh">{m.a.owner}</div></div><div className="stat"><b>{m.aProj.toFixed(1)}</b></div></div>
          <div className="mid">VS</div>
          <div className="half r"><FAvatar t={m.b} size={38} /><div style={{ minWidth: 0 }}><div className="nm">{m.b.name}</div><div className="fresh">{m.b.owner}</div></div><div className="stat"><b>{m.bProj.toFixed(1)}</b></div></div></div>))}</div>
        : <Empty title="No matchups loaded" icon="event_busy" />}
    </>
  )
}
