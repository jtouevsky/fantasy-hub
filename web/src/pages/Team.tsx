import { useState } from 'react'
import { useApi, post, qc } from '../api'
import { AskAI, Icon, Notice, PlayerRow, RecCard, Rows, Section, Skel, signed, useActions } from '../ui'

export default function Team() {
  const { data: d, isLoading } = useApi<any>('/api/team')
  const [preview, setPreview] = useState(false)
  const { toast } = useActions()
  if (isLoading || !d) return <Skel n={5} h={64} />
  const rows = preview ? d.optimal : d.current
  const starters = rows.filter((r: any) => r.p)
  const empties = rows.filter((r: any) => !r.p)
  const cur = new Set(d.current.filter((r: any) => r.p).map((r: any) => r.p.id))
  const outIds = new Set(d.movedOut)
  return (
    <>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'space-between', flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="kpis">
          <div className="kpi"><b>{d.currentTotal.toFixed(1)}</b><small>Current projected</small></div>
          <div className="kpi"><b>{d.optimalTotal.toFixed(1)}</b><small>Optimal projected</small></div>
          <div className="kpi"><b className={d.gain > 0.05 ? 'up' : ''}>{signed(d.gain)}</b><small>Possible gain</small></div>
        </div>
        <label className="toggle" title={d.hasSwaps ? 'Shows where each player would sit. Nothing is changed in ESPN.' : 'Your lineup is already optimal.'}>
          <input type="checkbox" checked={preview} disabled={!d.hasSwaps} onChange={(e) => setPreview(e.target.checked)} /> Preview the optimal lineup</label>
      </div>
      <Notice icon="lock"><b>Fantasy Hub is read-only.</b> Previews show recommendations; make the actual moves in the ESPN app.</Notice>
      {d.edgesOn && <Notice icon="bolt"><b>Edges on:</b> projections include adjustments for injuries, game environment, weather and opportunity. On ESPN's raw numbers your optimal lineup is {d.espnOptimal.toFixed(1)}; with edges {d.optimalTotal.toFixed(1)} ({signed(d.optimalTotal - d.espnOptimal)}).</Notice>}
      {d.alerts.map((a: any, i: number) => <Notice key={i} kind={a.tone} icon="schedule"><b>Re-check before lock</b> · {a.text}</Notice>)}
      {d.alerts.length > 0 && <div className="actions"><button className="btn sm" onClick={async () => { await post('/api/refresh'); qc.invalidateQueries(); toast('Re-checked') }}><Icon n="refresh" /> Re-check injuries &amp; re-run edges</button></div>}

      <Section title="Starters" aside={`${starters.length} of ${d.slotsTotal} slots filled`} />
      {starters.length ? <Rows label="Starters">{starters.map((r: any) => <PlayerRow key={r.p.id} p={r.p} slot={r.slot} moved={preview && !cur.has(r.p.id)} note={preview && !cur.has(r.p.id) ? ' · moves into lineup' : ''} />)}</Rows> : <Notice icon="groups">No starters set. Set your lineup in the ESPN app.</Notice>}
      {empties.map((r: any, i: number) => <Notice key={i} kind="bad" icon="person_off">Your <b>{r.slot}</b> slot is empty.</Notice>)}

      <Section title="Bench" aside={`${d.bench.length} of ${d.benchSlots} spots`} />
      <Rows label="Bench">{d.bench.map((p: any) => <PlayerRow key={p.id} p={p} slot="BN" moved={preview && outIds.has(p.id)} note={preview && outIds.has(p.id) ? ' · moves to bench' : ''} />)}</Rows>
      {(d.ir.length > 0 || d.irSlots > 0) && <><Section title="Injured reserve" aside={`${d.ir.length} of ${d.irSlots} spots`} /><Rows label="Injured reserve">{d.ir.map((p: any) => <PlayerRow key={p.id} p={p} slot="IR" />)}</Rows></>}

      {d.swaps.length > 0 && <>
        <Section title="Recommended changes" />
        {d.swaps.map((s: any, i: number) => <RecCard key={i} title={`${s.in.name} in, ${s.out ? s.out.name : 'an empty slot'} out`} body={s.reason} icon="swap_vert" gain={s.gain} gainLabel="proj pts" todo={s.action}
          players={[s.in, ...(s.out ? [s.out] : [])]} edgeNote={s.fromEdge ? `${s.edgeNote} (On ESPN's raw numbers this swap is worth ${signed(s.espnGain)}.)` : ''} />)}
        <div className="actions"><AskAI label="Explain these changes" prompt="Review my lineup and explain each recommended change simply." title="Lineup review" icon="fact_check" /></div></>}
    </>
  )
}
