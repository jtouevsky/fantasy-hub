import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi, post, qc } from '../api'
import { MetalButton } from '../fx'
import { AskAI, Avatar, Chip, Empty, FAvatar, Icon, Notice, Section, Skel, NflTag, TagChips, useActions } from '../ui'

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
    <>
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
        {t.ladder.length > 0 && <div className="ladder"><h5 style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--ink-3)', margin: '0 0 6px' }}>Offer ladder</h5><ol>{t.ladder.map((s: any, i: number) => (
          <li key={i} className="step"><span className="n">{i + 1}</span><div style={{ minWidth: 0 }}><b>{s.name}</b><div className="g">{s.give.join(' + ')}</div><div className="n2"><Chip kind={THEM[s.label][0]} icon={THEM[s.label][1]}>{s.label[0].toUpperCase() + s.label.slice(1)}</Chip><span className="num">{s.myDelta >= 0 ? '+' : ''}{s.myDelta} for you</span></div><small>{s.note}</small></div></li>))}</ol></div>}
        <div className="todo" style={{ marginTop: 12, display: 'flex', gap: 6, fontSize: 12.5, color: 'var(--ink-2)' }}><Icon n="arrow_forward" /><span>Do this in the ESPN app: open {t.other.name}'s team and propose this trade.</span></div>
      </article>
      <div className="hero-actions">
        <MetalButton icon="balance" label="Ask AI" size={52} onClick={() => askAI(`Evaluate this trade for me: I give ${names(t.give)} and get ${names(t.get)} from ${t.other.name}. Use evaluate_trade, answer 'should I offer it' and 'would they accept' separately, and show the offer ladder.`, 'Trade review')} />
        <MetalButton icon="chat" label="Draft message" size={52} onClick={() => setPitchOpen(!pitchOpen)} />
        <MetalButton icon="edit_note" label="Log answer" size={52} onClick={() => setLogOpen(!logOpen)} />
        <MetalButton icon="bookmark_add" label="Save" size={52} onClick={async () => { await post('/api/recommendations', { kind: 'trade', summary: `${names(t.give)} for ${names(t.get)} (${t.other.name})`, details: { my_delta: t.myDelta, acceptance: t.label } }); toast('Saved to your recommendation log.') }} />
      </div>
      {pitchOpen && <div className="field"><label>Pitch (edit, then send it yourself in ESPN). Nothing is sent automatically.</label><textarea rows={5} defaultValue={t.pitch} /></div>}
      {logOpen && <div className="form"><div className="field"><label>What did he say?</label><select value={resp} onChange={(e) => setResp(e.target.value)}>{['accepted', 'rejected', 'countered', 'no response'].map((x) => <option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Note (optional)</label><input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. wants a RB back" /></div><button className="btn primary" onClick={save}><Icon n="check" /> Save</button></div>}
    </>
  )
}

function MultiSel({ label, options, value, onChange, placeholder }: { label: string; options: { v: any; l: string }[]; value: any[]; onChange: (v: any[]) => void; placeholder?: string }) {
  return (
    <div className="field"><label>{label}</label>
      <select multiple value={value.map(String)} onChange={(e) => onChange([...e.target.selectedOptions].map((o) => (isNaN(Number(o.value)) ? o.value : Number(o.value))))} aria-label={label}>
        {options.map((o) => <option key={o.v} value={String(o.v)}>{o.l}</option>)}</select>
      {value.length === 0 && placeholder && <small className="fresh">{placeholder}</small>}</div>
  )
}

export default function Trades() {
  const { data: meta, isLoading } = useApi<any>('/api/trades/meta')
  const [mode, setMode] = useState('Find me a trade')
  return (
    <>
      <div className="pills" role="tablist">{['Find me a trade', 'Evaluate a deal', 'Negotiation log'].map((m) => <button key={m} className={`pill ${mode === m ? 'on' : ''}`} onClick={() => setMode(m)}>{m}</button>)}</div>
      {isLoading || !meta ? <Skel n={3} h={80} /> : mode === 'Find me a trade' ? <Find meta={meta} /> : mode === 'Evaluate a deal' ? <Evaluate meta={meta} /> : <Negotiations meta={meta} />}
    </>
  )
}

function Find({ meta }: { meta: any }) {
  const [text, setText] = useState('')
  const [partner, setPartner] = useState<number | ''>('')
  const [offering, setOffering] = useState<number[]>([])
  const [split, setSplit] = useState(60)
  const [want, setWant] = useState<string[]>([]), [nogive, setNogive] = useState<string[]>([])
  const [need, setNeed] = useState(''), [loss, setLoss] = useState(false), [notes, setNotes] = useState<string[]>([])
  const read = async () => {
    const r = await post('/api/trades/parse', { text })
    setPartner(r.partner ?? ''); setOffering(r.offering); setSplit(r.split); setWant(r.want); setNogive(r.nogive); setNeed(r.need || ''); setLoss(r.loss); setNotes(r.notes)
  }
  const body = { partner: partner === '' ? null : partner, offering, split, want, nogive, need, loss, max: 6 }
  const search = useQuery({ queryKey: ['/api/trades/search', body], queryFn: () => post('/api/trades/search', body), staleTime: 5 * 60_000, placeholderData: (p) => p })
  const others = meta.teams.filter((t: any) => !t.me)
  return (
    <>
      <div className="fresh" style={{ margin: '10px 0 6px' }}>Describe what you want in plain English, e.g. <i>find me a WR for the playoffs without giving up an RB, about 60/40</i>. I turn it into the settings below so you can correct anything before searching.</div>
      <div style={{ display: 'flex', gap: 8 }}><input className="field" style={{ flex: 1, height: 42, borderRadius: 999, border: '1px solid var(--line-strong)', padding: '0 16px', background: 'var(--solid)' }} type="text" value={text} placeholder="e.g. sell high on my RB for a receiver; no QBs" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && read()} aria-label="Trade request" />
        <MetalButton icon="auto_fix_high" label="Read it" onClick={read} size={46} /></div>
      {notes.length > 0 && <div className="ctxrow" style={{ marginTop: 8 }}><Chip icon="psychology">How I read that</Chip>{notes.map((n) => <Chip key={n}>{n}</Chip>)}</div>}
      <div className="form">
        <div className="field"><label>Trade with</label><select value={partner} onChange={(e) => setPartner(e.target.value === '' ? '' : Number(e.target.value))}><option value="">Anyone in the league</option>{others.map((t: any) => <option key={t.id} value={t.id}>{t.first ? `${t.first} · ` : ''}{t.name}</option>)}</select></div>
        <MultiSel label="Players I'd move (optional)" options={meta.mine.map((p: any) => ({ v: p.id, l: `${p.name} · ${p.pos} · ${p.team}` }))} value={offering} onChange={setOffering} placeholder="Let the search choose" />
        <div className="field"><label>My-value split: {split}</label><input type="range" min={50} max={70} value={split} onChange={(e) => setSplit(Number(e.target.value))} aria-label="My-value split" /></div>
      </div>
      <div className="form">
        <MultiSel label="Ask for" options={POS.map((p) => ({ v: p, l: p }))} value={want} onChange={setWant} placeholder="Any position" />
        <MultiSel label="Won't give" options={POS.map((p) => ({ v: p, l: p }))} value={nogive} onChange={setNogive} placeholder="None" />
        <div className="field"><label>Must help my</label><select value={need} onChange={(e) => setNeed(e.target.value)}><option value="">No requirement</option>{POS.map((p) => <option key={p}>{p}</option>)}</select></div>
        <label className="toggle"><input type="checkbox" checked={loss} onChange={(e) => setLoss(e.target.checked)} /> Sell / rebuild (lineup may dip)</label>
      </div>
      <div className="ctxrow">{search.data?.constraints.map((x: string) => <Chip key={x}>{x}</Chip>)}</div>
      {search.isLoading ? <><Notice icon="hourglass_top">Scanning every team for the cheapest offer that works...</Notice><Skel n={2} h={200} /></> :
        !search.data?.results.length ? <Notice kind="warn" icon="search_off">No trade clears both questions (good for you AND plausible for him) under these settings. Loosen the split, drop a position filter, or allow a sell/rebuild move.</Notice> :
          <><Section title={`${search.data.results.length} option${search.data.results.length !== 1 ? 's' : ''}`} aside="cheapest winning offer first" />{search.data.results.map((t: any, i: number) => <Offer key={i} t={t} k={`f${i}`} />)}</>}
    </>
  )
}

function Evaluate({ meta }: { meta: any }) {
  const others = meta.teams.filter((t: any) => !t.me)
  const [partner, setPartner] = useState<number>(others[0]?.id)
  const [give, setGive] = useState<number[]>([]), [get, setGet] = useState<number[]>([])
  const other = others.find((t: any) => t.id === partner)
  const ev = useQuery({ queryKey: ['/api/trades/evaluate', partner, give, get], queryFn: () => post('/api/trades/evaluate', { partner, give, get }), enabled: give.length > 0 && get.length > 0, staleTime: 5 * 60_000 })
  useEffect(() => setGet([]), [partner])
  return (
    <>
      <div className="form"><div className="field"><label>Trade with</label><select value={partner} onChange={(e) => setPartner(Number(e.target.value))}>{others.map((t: any) => <option key={t.id} value={t.id}>{t.first ? `${t.first} · ` : ''}{t.name}</option>)}</select></div></div>
      <div className="form"><MultiSel label="You give" options={meta.mine.map((p: any) => ({ v: p.id, l: `${p.name} · ${p.pos} · ${p.team}` }))} value={give} onChange={setGive} />
        <MultiSel label="You get" options={(other?.players || []).map((p: any) => ({ v: p.id, l: `${p.name} · ${p.pos} · ${p.team}` }))} value={get} onChange={setGet} /></div>
      {give.length && get.length ? (ev.isLoading ? <Skel n={1} h={240} /> : ev.data ? <Offer t={ev.data} k="eval" /> : null) : <Empty title="Pick players on both sides" body="I'll answer two separate questions: should you offer it, and would he accept." icon="swap_horiz" />}
    </>
  )
}

function Negotiations({ meta }: { meta: any }) {
  const others = meta.teams.filter((t: any) => !t.me)
  const [team, setTeam] = useState<number>(others[0]?.id)
  const [give, setGive] = useState<number[]>([]), [get, setGet] = useState<number[]>([]), [resp, setResp] = useState('accepted'), [note, setNote] = useState('')
  const { toast } = useActions()
  const { data: n } = useApi<any>(`/api/trades/negotiations?team=${team}`, { stale: 0 })
  const other = others.find((t: any) => t.id === team)
  const save = async () => { await post('/api/trades/negotiations', { team, give, get, response: resp, note }); qc.invalidateQueries({ queryKey: [`/api/trades/negotiations?team=${team}`] }); setGive([]); setGet([]); setNote(''); toast('Logged.') }
  return (
    <>
      <div className="form"><div className="field"><label>Manager</label><select value={team} onChange={(e) => setTeam(Number(e.target.value))}>{others.map((t: any) => <option key={t.id} value={t.id}>{t.first ? `${t.first} · ` : ''}{t.name}</option>)}</select></div></div>
      {n && <><div className="ctxrow"><FAvatar t={n.team} size={28} /><b>{n.team.name}</b><Chip icon="sports_score">{n.team.record}</Chip><Chip icon="swap_horiz">{n.profile.trades_this_season} trades this season</Chip><Chip icon="person_add">{n.profile.adds} adds · {n.profile.drops} drops</Chip>
        <Chip icon="history">Logged: {n.profile.logged.accepted} yes · {n.profile.logged.rejected} no · {n.profile.logged.countered} counter</Chip></div>
        <Notice icon="psychology">Tendency: {n.profile.tendency_text}.</Notice></>}
      <Section title="Add an answer" aside="what he actually said" />
      <div className="form"><MultiSel label="I offered" options={meta.mine.map((p: any) => ({ v: p.id, l: `${p.name} · ${p.pos} · ${p.team}` }))} value={give} onChange={setGive} />
        <MultiSel label="I asked for" options={(other?.players || []).map((p: any) => ({ v: p.id, l: `${p.name} · ${p.pos} · ${p.team}` }))} value={get} onChange={setGet} /></div>
      <div className="form"><div className="field"><label>He said</label><select value={resp} onChange={(e) => setResp(e.target.value)}>{['accepted', 'rejected', 'countered', 'no response'].map((x) => <option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Note</label><input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. 'would do it if I add a WR3'" /></div>
        <button className="btn primary" disabled={!(give.length && get.length)} onClick={save}><Icon n="check" /> Save</button></div>
      <Section title="History" />
      {!n?.rows.length ? <Empty title="Nothing logged with this manager yet" body="Log what he says to your offers; confirmed answers override the estimate for that same ask." icon="history" /> :
        n.rows.map((r: any) => <div key={r.id} className="neg"><Chip kind={{ accepted: 'good', rejected: 'bad', countered: 'warn' }[r.response as string] || ''}>{r.response[0].toUpperCase() + r.response.slice(1)}</Chip><span><b>{r.give}</b> for <b>{r.get}</b>{r.note ? ` · ${r.note}` : ''}</span><small>{r.ts}</small></div>)}
    </>
  )
}
