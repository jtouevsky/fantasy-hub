import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi, post, qc } from '../api'
import { Spinner } from '../fx'
import { Avatar, Chip, Empty, FAvatar, Icon, Notice, Section, Skel, NflTag, TagChips, useActions } from '../ui'
import { Quick, RosterPicker, Seg, Switch, TeamPicker, Tray, toggle } from '../pick'

const POS = ['QB', 'RB', 'WR', 'TE']
const ME: Record<string, [string, string]> = { good: ['good', 'thumb_up'], marginal: ['warn', 'balance'], no: ['bad', 'thumb_down'] }
const THEM: Record<string, [string, string]> = { likely: ['good', 'thumb_up'], 'coin flip': ['warn', 'help'], unlikely: ['bad', 'thumb_down'] }

function Side({ players }: { players: any[] }) {
  return <>{players.map((p) => (
    <div key={p.id} className="p" style={{ '--tc': p.color } as any}><Avatar p={p} size={40} />
      <div style={{ minWidth: 0 }}><div className="nm">{p.name}</div>
        <div className="sub"><Chip kind="pos">{p.pos}</Chip><NflTag abbr={p.team} /></div>
        <div className="sub">{p.tl && <Chip kind="warn" icon="personal_injury">{p.tl}</Chip>}<TagChips p={p} /></div></div></div>))}</>
}

function Offer({ t, k }: { t: any; k: string }) {
  const { toast, askAI } = useActions()
  const [resp, setResp] = useState('accepted'), [note, setNote] = useState(''), [logOpen, setLogOpen] = useState(false), [pitchOpen, setPitchOpen] = useState(false)
  const [mk, mi] = [ME[t.verdictMe], THEM[t.label]]
  const pro = t.signals.filter((x: any) => x.effect >= 0.1), con = t.signals.filter((x: any) => x.effect <= -0.1)
  const save = async () => {
    await post('/api/trades/negotiations', { team: t.other.id, give: t.giveIds, get: t.getIds, response: resp, note })
    qc.invalidateQueries({ queryKey: ['/api/trades/negotiations'] }); setLogOpen(false); toast('Logged. Future estimates for this manager will use it.')
  }
  const names = (a: any[]) => a.map((p) => p.name).join(' + ')
  return (
    <div className="offer-wrap">
      <article className="offer">
        <div className="ctxrow"><Chip kind="pos">{t.kind}</Chip><Chip kind={mk[0]} icon={mk[1]}>{t.verdictMeText}</Chip><Chip kind={mi[0]} icon={mi[1]}>{t.label[0].toUpperCase() + t.label.slice(1)} to accept</Chip>
          {t.confirmed && <Chip kind="good" icon="verified">Confirmed by manager</Chip>}{t.speculative && <Chip kind="warn" icon="bolt">Speculative</Chip>}</div>
        <div className="sides"><div className="col"><h5>You give</h5><Side players={t.give} /></div><div className="swap"><Icon n="swap_horiz" /></div><div className="col"><h5>You get from {t.other.name}</h5><Side players={t.get} /></div></div>
        <div className="vals">
          <div className="val"><h6>My value <small>should I offer it?</small></h6><div className={`big num ${t.myDelta > 0 ? 'up' : t.myDelta < 0 ? 'dn' : ''}`}>{t.myDelta >= 0 ? '+' : ''}{t.myDelta}</div>
            <small>weighted points to your lineup, rest of season ({t.myAvgWeek >= 0 ? '+' : ''}{t.myAvgWeek}/wk)</small><div className="track" role="img" aria-label={`My value split ${t.mySplit} to ${100 - t.mySplit}`}><i style={{ width: `${t.mySplit}%` }} /></div><div className="lbl"><span>You {t.mySplit}</span><span>{100 - t.mySplit} Them</span></div></div>
          <div className="val"><h6>Market value <small>would they accept?</small></h6><div className="big num">{t.marketTheirs}<small>% to him</small></div>
            <small>what his league sees: ADP, consensus rank, ownership; plus his needs</small><div className="track" role="img" aria-label={`Market split ${100 - t.marketTheirs} to ${t.marketTheirs}`}><i style={{ width: `${100 - t.marketTheirs}%` }} /></div><div className="lbl"><span>You {100 - t.marketTheirs}</span><span>{t.marketTheirs} Them</span></div></div>
        </div>
        <div className="wkhead">Your lineup, week by week <small>(expected points change; playoff weeks count 1.5x)</small></div>
        <div className="wkrow">{t.weeks.map((w: any) => <div key={w.w} className={`wk ${w.d > 0.05 ? 'up' : w.d < -0.05 ? 'dn' : ''} ${w.mark === 'playoffs' ? 'po' : ''}`} title={`Week ${w.w}: ${w.before} to ${w.after} expected points`}><small>W{w.w}</small><b>{w.d >= 0 ? '+' : ''}{w.d.toFixed(1)}</b><i>{w.mark}</i></div>)}</div>
        <div className="why2"><div><h5>His side: for and against</h5><ul>{t.confirmed && <li><i>{t.confirmed}</i></li>}{pro.map((x: any) => <li key={x.name}><b className="up">+</b> {x.name}: {x.text}</li>)}{con.map((x: any) => <li key={x.name}><b className="dn">-</b> {x.name}: {x.text}</li>)}{!t.confirmed && !pro.length && !con.length && <li>No strong signals either way.</li>}</ul></div>
          <div><h5>Risk and notes</h5><ul>{[...t.risk, ...t.notes].map((r: string, i: number) => <li key={i}>{r}</li>)}{!t.risk.length && !t.notes.length && <li>Nothing unusual.</li>}</ul></div></div>
        {t.ladder.length > 0 && <div className="ladder"><h5 style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)', margin: '0 0 6px' }}>Offer ladder</h5><ol>{t.ladder.map((s: any, i: number) => (
          <li key={i} className="step"><span className="n">{i + 1}</span><div style={{ minWidth: 0 }}><b>{s.name}</b><div className="g">{s.give.join(' + ')}</div><div className="n2"><Chip kind={THEM[s.label][0]} icon={THEM[s.label][1]}>{s.label[0].toUpperCase() + s.label.slice(1)}</Chip><span className="num">{s.myDelta >= 0 ? '+' : ''}{s.myDelta} for you</span></div><small>{s.note}</small></div></li>))}</ol></div>}
        <div className="todo" style={{ marginTop: 12, display: 'flex', gap: 6, fontSize: 12.5, color: 'var(--muted)' }}><Icon n="arrow_forward" /><span>Do this in the ESPN app: open {t.other.name}'s team and propose this trade.</span></div>
      </article>
      <div className="hero-actions">
        <button className="btn sm" onClick={() => askAI(`Evaluate this trade for me: I give ${names(t.give)} and get ${names(t.get)} from ${t.other.name}. Use evaluate_trade, answer 'should I offer it' and 'would they accept' separately, and show the offer ladder.`, 'Trade review')}><Icon n="balance" /> Ask AI</button>
        <button className="btn sm" onClick={() => setPitchOpen(!pitchOpen)}><Icon n="chat" /> Draft message</button>
        <button className="btn sm" onClick={() => setLogOpen(!logOpen)}><Icon n="edit_note" /> Log answer</button>
        <button className="btn sm" onClick={async () => { await post('/api/recommendations', { kind: 'trade', summary: `${names(t.give)} for ${names(t.get)} (${t.other.name})`, details: { my_delta: t.myDelta, acceptance: t.label } }); toast('Saved to your recommendation log.') }}><Icon n="bookmark_add" /> Save</button>
      </div>
      {pitchOpen && <div className="field"><label>Pitch (edit, then send it yourself in ESPN). Nothing is sent automatically.</label><textarea rows={5} defaultValue={t.pitch} /></div>}
      {logOpen && <div className="form"><div className="field"><label>What did he say?</label><select value={resp} onChange={(e) => setResp(e.target.value)}>{['accepted', 'rejected', 'countered', 'no response'].map((x) => <option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Note (optional)</label><input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. wants a RB back" /></div><button className="btn primary shine" onClick={save}><Icon n="check" /> Save</button></div>}
    </div>
  )
}

const MODES = ['Find me a trade', 'Evaluate a deal', 'Negotiation log']
const ASK = [
  { icon: 'person_search', text: 'Who is most likely to accept a trade?', prompt: 'Which managers in my league are most likely to accept a trade right now, and what do they need? Use the trade tools.' },
  { icon: 'sell', text: 'Best sell-high on my team', prompt: 'Which of my players should I sell high on, and who could I realistically get back? Show the offer ladder.' },
  { icon: 'trending_up', text: 'Upgrade my weakest starter', prompt: 'Find me a trade that upgrades my weakest starting spot, slightly in my favor, that the other manager would plausibly accept.' },
  { icon: 'shield', text: 'Trade for the playoffs', prompt: 'Find me a trade that helps my lineup most in the fantasy playoff weeks, and tell me what it costs now.' },
]

export default function Trades() {
  const { data: meta, isLoading } = useApi<any>('/api/trades/meta')
  const [mode, setMode] = useState(MODES[0])
  const { askAI } = useActions()
  return (
    <>
      <div className="ask-strip"><Seg label="Trade tools" value={mode} onChange={setMode} options={[{ v: MODES[0], l: <><Icon n="auto_awesome" />Find me a trade</> }, { v: MODES[1], l: <><Icon n="balance" />Evaluate a deal</> }, { v: MODES[2], l: <><Icon n="history" />Negotiation log</> }]} /></div>
      <Quick items={ASK} onPick={(prompt, text) => askAI(prompt, text)} />
      {isLoading || !meta ? <Skel n={3} h={80} /> : mode === MODES[0] ? <Find meta={meta} /> : mode === MODES[1] ? <Evaluate meta={meta} /> : <Negotiations meta={meta} />}
    </>
  )
}

const FIND_IDEAS = [
  { icon: 'trending_up', text: 'Find me a WR without giving up an RB' },
  { icon: 'sell', text: 'Sell high on my RB for a receiver' },
  { icon: 'shield', text: 'Upgrade my TE, about 60/40' },
  { icon: 'swap_horiz', text: 'Find me a QB, no RBs' },
]

function Find({ meta }: { meta: any }) {
  const [text, setText] = useState('')
  const [partner, setPartner] = useState<number | ''>('')
  const [offering, setOffering] = useState<number[]>([])
  const [split, setSplit] = useState(60)
  const [want, setWant] = useState<string[]>([]), [nogive, setNogive] = useState<string[]>([])
  const [need, setNeed] = useState(''), [loss, setLoss] = useState(false), [notes, setNotes] = useState<string[]>([])
  const [reading, setReading] = useState(false)
  const read = async (t = text) => {
    if (!t.trim() || reading) return
    setReading(true)
    try {
      const r = await post('/api/trades/parse', { text: t })
      setPartner(r.partner ?? ''); setOffering(r.offering); setSplit(r.split); setWant(r.want); setNogive(r.nogive); setNeed(r.need || ''); setLoss(r.loss); setNotes(r.notes)
    } finally { setReading(false) }
  }
  const body = { partner: partner === '' ? null : partner, offering, split, want, nogive, need, loss, max: 6 }
  const search = useQuery({ queryKey: ['/api/trades/search', body], queryFn: () => post('/api/trades/search', body), staleTime: 5 * 60_000, placeholderData: (p) => p })
  const others = meta.teams.filter((t: any) => !t.me)
  const togglePos = (list: string[], set: (v: string[]) => void, p: string) => set(list.includes(p) ? list.filter((x) => x !== p) : [...list, p])
  return (
    <>
      <form className="find-box" onSubmit={(e) => { e.preventDefault(); read() }}>
        <input type="text" value={text} placeholder="Tell me what you want, e.g. find me a WR for the playoffs without giving up an RB" onChange={(e) => setText(e.target.value)} aria-label="Trade request" />
        <button className={`btn primary shine ${reading ? 'busy' : ''}`} type="submit" disabled={reading}>{reading ? <Spinner /> : <Icon n="auto_fix_high" />} Find it</button>
      </form>
      <div style={{ height: 12 }} />
      <Quick items={FIND_IDEAS} onPick={(t) => { setText(t); read(t) }} />
      {notes.length > 0 && <div className="ctxrow" style={{ marginBottom: 12 }}><Chip icon="psychology">How I read that</Chip>{notes.map((n) => <Chip key={n}>{n}</Chip>)}</div>}
      <span className="lbl2" style={{ marginTop: 4 }}>Trade with</span>
      <TeamPicker teams={others} value={partner} onChange={setPartner} any="Anyone" />
      <details className="tune"><summary><Icon n="chevron_right" /> Fine-tune the search{(want.length || nogive.length || need || loss || offering.length) ? <Chip kind="ai">Customized</Chip> : null}</summary>
        <div className="form">
          <div><span className="lbl2" style={{ marginTop: 0 }}>Ask for (none = any)</span><div className="seg" role="group" aria-label="Ask for">{POS.map((p) => <button type="button" key={p} aria-pressed={want.includes(p)} onClick={() => togglePos(want, setWant, p)}>{p}</button>)}</div></div>
          <div><span className="lbl2" style={{ marginTop: 0 }}>I won't give</span><div className="seg" role="group" aria-label="Won't give">{POS.map((p) => <button type="button" key={p} aria-pressed={nogive.includes(p)} onClick={() => togglePos(nogive, setNogive, p)}>{p}</button>)}</div></div>
          <div><span className="lbl2" style={{ marginTop: 0 }}>Must help my</span><Seg label="Must help my" value={need} onChange={setNeed} options={[{ v: '', l: 'Anything' }, ...POS.map((p) => ({ v: p, l: p }))]} /></div>
          <div><span className="lbl2" style={{ marginTop: 0 }}>My-value split: {split}</span><input type="range" min={50} max={70} value={split} onChange={(e) => setSplit(Number(e.target.value))} aria-label="My-value split" style={{ width: '100%' }} /></div>
          <Switch on={loss} onChange={setLoss}>Sell / rebuild (lineup may dip)</Switch>
        </div>
        <div style={{ padding: '0 16px 16px' }}><span className="lbl2" style={{ marginTop: 0 }}>Players I'd move (optional, tap to pick)</span>
          <RosterPicker title="My roster" players={meta.mine} selected={offering} onToggle={(id) => setOffering(toggle(offering, id))} /></div>
      </details>
      <div className="ctxrow">{search.data?.constraints.map((x: string) => <Chip key={x}>{x}</Chip>)}</div>
      {search.isLoading ? <><Notice icon="hourglass_top">Scanning every team for the cheapest offer that works...</Notice><Skel n={2} h={200} /></> :
        !search.data?.results.length ? <Notice kind="warn" icon="search_off">No trade clears both questions (good for you AND plausible for him) under these settings. Loosen the split, drop a position filter, or allow a sell/rebuild move.</Notice> :
          <><Section title={`${search.data.results.length} option${search.data.results.length !== 1 ? 's' : ''}`} aside="cheapest winning offer first" /><div className="offers">{search.data.results.map((t: any, i: number) => <Offer key={i} t={t} k={`f${i}`} />)}</div></>}
    </>
  )
}

/** Both rosters side by side plus the deal tray; shared by Evaluate and the negotiation log. */
function DealBuilder({ meta, partner, setPartner, give, get, setGive, setGet, giveLabel, getLabel }: { meta: any; partner: number; setPartner: (n: number) => void; give: number[]; get: number[]; setGive: (v: number[]) => void; setGet: (v: number[]) => void; giveLabel?: string; getLabel?: string }) {
  const others = meta.teams.filter((t: any) => !t.me)
  const other = others.find((t: any) => t.id === partner)
  const me = meta.teams.find((t: any) => t.me)
  const byId = (list: any[], ids: number[]) => ids.map((id) => list.find((p) => p.id === id)).filter(Boolean)
  return (
    <>
      <span className="lbl2" style={{ marginTop: 0 }}>Trade with</span>
      <TeamPicker teams={others} value={partner} onChange={(v) => { if (v !== '') { setPartner(v); setGet([]) } }} />
      <Tray give={byId(meta.mine, give)} get={byId(other?.players || [], get)} giveLabel={giveLabel} getLabel={getLabel} onRemoveGive={(id) => setGive(give.filter((x) => x !== id))} onRemoveGet={(id) => setGet(get.filter((x) => x !== id))} onClear={() => { setGive([]); setGet([]) }} />
      <div className="rosters">
        <RosterPicker title="Your roster" team={me} players={meta.mine} selected={give} onToggle={(id) => setGive(toggle(give, id))} />
        <RosterPicker title={other?.first ? `${other.first}'s roster` : other?.name || 'Their roster'} team={other} players={other?.players || []} selected={get} onToggle={(id) => setGet(toggle(get, id))} />
      </div>
    </>
  )
}

function Evaluate({ meta }: { meta: any }) {
  const others = meta.teams.filter((t: any) => !t.me)
  const [partner, setPartner] = useState<number>(others[0]?.id)
  const [give, setGive] = useState<number[]>([]), [get, setGet] = useState<number[]>([])
  const ev = useQuery({ queryKey: ['/api/trades/evaluate', partner, give, get], queryFn: () => post('/api/trades/evaluate', { partner, give, get }), enabled: give.length > 0 && get.length > 0, staleTime: 5 * 60_000 })
  return (
    <>
      <DealBuilder meta={meta} partner={partner} setPartner={setPartner} give={give} get={get} setGive={setGive} setGet={setGet} />
      <div style={{ height: 16 }} />
      {give.length && get.length ? (ev.isLoading ? <Skel n={1} h={240} /> : ev.data ? <Offer t={ev.data} k="eval" /> : null) : <Empty title="Tap players on both sides" body="I'll answer two separate questions: should you offer it, and would he accept." icon="swap_horiz" />}
    </>
  )
}

function Negotiations({ meta }: { meta: any }) {
  const others = meta.teams.filter((t: any) => !t.me)
  const [team, setTeam] = useState<number>(others[0]?.id)
  const [give, setGive] = useState<number[]>([]), [get, setGet] = useState<number[]>([]), [resp, setResp] = useState('accepted'), [note, setNote] = useState('')
  const { toast } = useActions()
  const { data: n } = useApi<any>(`/api/trades/negotiations?team=${team}`, { stale: 0 })
  const save = async () => { await post('/api/trades/negotiations', { team, give, get, response: resp, note }); qc.invalidateQueries({ queryKey: [`/api/trades/negotiations?team=${team}`] }); setGive([]); setGet([]); setNote(''); toast('Logged.') }
  return (
    <>
      {n && <><div className="ctxrow"><FAvatar t={n.team} size={28} /><b>{n.team.name}</b><Chip icon="sports_score">{n.team.record}</Chip><Chip icon="swap_horiz">{n.profile.trades_this_season} trades this season</Chip><Chip icon="person_add">{n.profile.adds} adds · {n.profile.drops} drops</Chip>
        <Chip icon="history">Logged: {n.profile.logged.accepted} yes · {n.profile.logged.rejected} no · {n.profile.logged.countered} counter</Chip></div>
        <Notice icon="psychology">Tendency: {n.profile.tendency_text}.</Notice></>}
      <Section title="Add an answer" aside="what he actually said" />
      <DealBuilder meta={meta} partner={team} setPartner={setTeam} give={give} get={get} setGive={setGive} setGet={setGet} giveLabel="I offered" getLabel="I asked for" />
      <div className="form" style={{ alignItems: 'end' }}>
        <div><span className="lbl2" style={{ marginTop: 0 }}>He said</span><Seg label="He said" value={resp} onChange={setResp} options={['accepted', 'rejected', 'countered', 'no response'].map((x) => ({ v: x, l: x[0].toUpperCase() + x.slice(1) }))} /></div>
        <div className="field"><label>Note</label><input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. 'would do it if I add a WR3'" /></div>
        <button className="btn primary shine" disabled={!(give.length && get.length)} onClick={save}><Icon n="check" /> Save</button></div>
      <Section title="History" />
      {!n?.rows.length ? <Empty title="Nothing logged with this manager yet" body="Log what he says to your offers; confirmed answers override the estimate for that same ask." icon="history" /> :
        n.rows.map((r: any) => <div key={r.id} className="neg"><Chip kind={{ accepted: 'good', rejected: 'bad', countered: 'warn' }[r.response as string] || ''}>{r.response[0].toUpperCase() + r.response.slice(1)}</Chip><span><b>{r.give}</b> for <b>{r.get}</b>{r.note ? ` · ${r.note}` : ''}</span><small>{r.ts}</small></div>)}
    </>
  )
}
