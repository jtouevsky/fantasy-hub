import { useMemo, useState, type ReactNode } from 'react'
import { Avatar, FAvatar, Icon, NflTag } from './ui'

/** Segmented control: one row of mutually exclusive choices (or a multi-select group when `multi`). */
export function Seg<T extends string>({ options, value, onChange, label }: { options: { v: T; l: ReactNode }[]; value: T; onChange: (v: T) => void; label: string }) {
  return <div className="seg" role="group" aria-label={label}>{options.map((o) => <button type="button" key={o.v} aria-pressed={value === o.v} onClick={() => onChange(o.v)}>{o.l}</button>)}</div>
}

export function Switch({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return <button type="button" role="switch" aria-checked={on} className="switch" onClick={() => onChange(!on)}><i />{children}</button>
}

/** One click per manager. `any` adds a leading "Anyone in the league" choice (value ''). */
export function TeamPicker({ teams, value, onChange, any }: { teams: any[]; value: number | ''; onChange: (v: number | '') => void; any?: string }) {
  return (
    <div className="teams" role="group" aria-label="Trade partner">
      {any && <button type="button" className="team-pick" aria-pressed={value === ''} onClick={() => onChange('')}><span className="any"><Icon n="groups" /></span><span style={{ minWidth: 0 }}><b>{any}</b><small>Let the search choose</small></span></button>}
      {teams.map((t) => (
        <button type="button" key={t.id} className="team-pick" aria-pressed={value === t.id} onClick={() => onChange(t.id)}>
          <FAvatar t={t} size={36} /><span style={{ minWidth: 0 }}><b>{t.first || t.name}</b><small>{t.first ? t.name : t.record}</small></span>
        </button>))}
    </div>
  )
}

const POS = ['All', 'QB', 'RB', 'WR', 'TE'] as const

/** A roster as tappable tiles: tap to add a player to the deal, tap again to remove. */
export function RosterPicker({ title, team, players, selected, onToggle }: { title: string; team?: any; players: any[]; selected: number[]; onToggle: (id: number) => void }) {
  const [pos, setPos] = useState<(typeof POS)[number]>('All')
  const shown = useMemo(() => players.filter((p) => pos === 'All' || p.pos === pos), [players, pos])
  const have = POS.slice(1).filter((x) => players.some((p) => p.pos === x))
  return (
    <section className="roster" aria-label={title}>
      <div className="roster-h"><h4>{team && <FAvatar t={team} size={24} />}{title}<small>{selected.length ? `${selected.length} selected` : `${players.length} players`}</small></h4></div>
      <Seg label={`${title} position`} value={pos} onChange={setPos} options={[{ v: 'All', l: 'All' }, ...have.map((x) => ({ v: x, l: x }))]} />
      <div className="tiles">
        {shown.map((p) => {
          const on = selected.includes(p.id)
          return (
            <button type="button" key={p.id} className="tile" aria-pressed={on} aria-label={`${p.name}, ${p.pos}, ${p.team}`} onClick={() => onToggle(p.id)} style={{ '--tc': p.color } as any}>
              <Avatar p={p} size={36} /><span className="tx"><b>{p.name}</b><small>{p.pos}<NflTag abbr={p.team} /></small></span>
              <span className="pj num" title="Projected points this week">{p.proj}</span><span className="ck"><Icon n="check" /></span>
            </button>)
        })}
        {!shown.length && <span className="none fresh">Nobody at this position.</span>}
      </div>
    </section>
  )
}

/** The deal so far: both sides as removable chips, with a clear button. */
export function Tray({ give, get, giveLabel = 'You give', getLabel = 'You get', onRemoveGive, onRemoveGet, onClear }: { give: any[]; get: any[]; giveLabel?: string; getLabel?: string; onRemoveGive: (id: number) => void; onRemoveGet: (id: number) => void; onClear: () => void }) {
  const Chips = ({ list, remove }: { list: any[]; remove: (id: number) => void }) => <div className="slot">{list.length ? list.map((p) => <span key={p.id} className="chip-p"><Avatar p={p} size={26} />{p.name}<button type="button" aria-label={`Remove ${p.name}`} onClick={() => remove(p.id)}><Icon n="close" /></button></span>) : <span className="none">Tap players below</span>}</div>
  return (
    <div className="tray" aria-live="polite">
      <div><h5>{giveLabel}</h5><Chips list={give} remove={onRemoveGive} /></div>
      <div className="mid"><span className="swapb shine"><Icon n="swap_horiz" /></span></div>
      <div><h5>{getLabel}</h5><Chips list={get} remove={onRemoveGet} /></div>
      {(give.length > 0 || get.length > 0) && <div className="clear"><span className="fresh">{give.length} for {get.length}</span><button type="button" className="btn sm ghost" onClick={onClear}><Icon n="delete_sweep" /> Clear</button></div>}
    </div>
  )
}

/** Horizontal row of one-click prompts. */
export function Quick({ items, onPick }: { items: { icon: string; text: string; prompt?: string }[]; onPick: (prompt: string, text: string) => void }) {
  return <div className="quick" role="group" aria-label="Quick prompts">{items.map((q) => <button type="button" key={q.text} className="qchip" onClick={() => onPick(q.prompt || q.text, q.text)}><Icon n={q.icon} />{q.text}</button>)}</div>
}

export const toggle = (list: number[], id: number) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
