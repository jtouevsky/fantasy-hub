import { Link } from 'react-router-dom'
import { useApi } from './api'
import { HeroButton } from './fx'
import { Avatar, Icon, Notice, Section, Skel, signed, useActions } from './ui'

/** The wide-screen right panel when no player is open: what to do next, a standings glance and a one-tap question for the assistant. All from data the Overview already cached. */
export default function ContextPanel() {
  const { data: d, isLoading } = useApi<any>('/api/overview')
  const { askAI } = useActions()
  if (isLoading || !d) return <div className="panel-in"><Skel n={3} h={70} /></div>
  return (
    <div className="panel-in">
      <h2 className="panel-h">Next up</h2>
      {d.swaps.length === 0 && d.moves.moves.length === 0 && !d.moves.streams.some((s: any) => s.swap)
        ? <Notice kind="good" icon="check_circle"><b>Nothing urgent.</b> Your lineup is set.</Notice> : null}
      {d.swaps.slice(0, 3).map((s: any, i: number) => (
        <div key={i} className="mini"><Avatar p={s.in} size={36} /><div className="mt"><b>Start {s.in.name}</b><small>{s.out ? `over ${s.out.name}` : 'fills an empty slot'}</small></div><span className="gainpill">{signed(s.gain)}</span></div>))}
      {d.moves.moves.slice(0, 2).map((m: any) => (
        <div key={m.add_id} className="mini mini-move"><Avatar p={m.addP} size={36} /><div className="mt"><b>Add {m.add}</b><small>{m.drop ? `drop ${m.drop} · ` : ''}rest of season {signed(m.gain_rest_of_season)} · {m.confidence} confidence</small></div></div>))}
      {d.moves.streams.map((s: any) => <Notice key={s.position} kind="good" icon={s.swap ? 'autorenew' : 'check_circle'}>{s.swap ? <><b>Stream {s.position}:</b> add {s.best}</> : <b>Keep your current {s.position}.</b>}</Notice>)}
      <Section title="Ask the assistant" />
      <div className="ask-grid">
        <HeroButton icon="fact_check" label="Review lineup" size={46} onClick={() => askAI('Review my lineup for this week: who to start and sit and why.', 'Lineup review')} />
        <HeroButton icon="newspaper" label="Summarize news" size={46} onClick={() => askAI('Summarize the news and injuries affecting my roster this week and what I should do before lock.', 'News summary')} />
        <HeroButton icon="swap_horiz" label="Find a trade" size={46} onClick={() => askAI('Scan the whole league for a trade that helps my lineup, about 60/40 in my value, that the other manager would plausibly accept.', 'Trade ideas')} />
      </div>
      <Section title="League standing" aside={<Link to="/league">Full league</Link>} />
      <div className="mini-list">{d.standings.map((t: any) => (
        <div key={t.id} className={`mini ${t.me ? 'me' : ''}`}><span className="rk num">{t.standing}</span><div className="mt"><b>{t.name}</b><small>{t.owner}</small></div><span className="num rec-s">{t.record}</span></div>))}</div>
      <div className="fresh" style={{ marginTop: 10 }}><Icon n="touch_app" /> Click any player to see him here.</div>
    </div>
  )
}
