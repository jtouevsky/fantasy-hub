import { useDeferredValue, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useApi } from '../api'
import { Chip, Empty, MovesBlock, PlayerRow, Section, Skel, Icon } from '../ui'
import type { Player } from '../types'

const SORTS = ['Rest of season', 'This week', 'Trending']

export default function Players() {
  const { data: d, isLoading } = useApi<any>('/api/players')
  const [pos, setPos] = useState('All')
  const [sort, setSort] = useState('Rest of season')
  const [q, setQ] = useState('')
  const [healthy, setHealthy] = useState(false)
  const [tag, setTag] = useState('')
  const dq = useDeferredValue(q)
  const rows: Player[] = useMemo(() => {
    if (!d) return []
    const ql = dq.toLowerCase()
    const r = d.fas.filter((p: Player) => (pos === 'All' || p.pos === pos) && (!healthy || p.healthy) && (!tag || p.tags.some((t) => t[0] === tag.toLowerCase())) &&
      (!ql || p.name.toLowerCase().includes(ql) || p.team.toLowerCase().includes(ql)))
    const key = sort === 'This week' ? (p: Player) => p.proj : sort === 'Trending' ? (p: Player) => (p.trend || 0) * 1000 + (p.key || 0) : (p: Player) => p.key || 0
    return [...r].sort((a, b) => key(b) - key(a))
  }, [d, pos, sort, dq, healthy, tag])
  const parent = useRef<HTMLDivElement>(null)
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 72, overscan: 8 })
  if (isLoading || !d) return <Skel n={5} h={90} />
  const top = Math.max(1, ...rows.map((r) => r.ros || 0))
  return (
    <>
      <div className="ctxrow">
        {d.waiverRank > 0 && <Chip icon="format_list_numbered">Waiver priority #{d.waiverRank}</Chip>}
        {d.faab > 0 && <Chip icon="payments">FAAB ${d.faabLeft} of ${d.faab}</Chip>}
        {d.waiverDays?.length > 0 && <Chip icon="event">Waivers run {d.waiverDays.map((x: string) => x.slice(0, 3)).join(', ')}</Chip>}
      </div>
      <Section title="Suggested moves" aside="from your strategy rules; same engine as the assistant" />
      <MovesBlock moves={d.moves} />
      {d.watch.length > 0 && <><Section title="Watchlist" aside={`${d.watch.length} saved player${d.watch.length !== 1 ? 's' : ''}`} />
        <div className="rows">{d.watch.map((p: Player) => <PlayerRow key={p.id} p={p} showActual={false} note={` · ${p.where}`} whyOpen={false} />)}</div></>}
      <Section title="Browse free agents" />
      <div className="pills" role="group" aria-label="Position">{['All', ...d.positions].map((x: string) => <button key={x} className={`pill ${pos === x ? 'on' : ''}`} onClick={() => setPos(x)}>{x}</button>)}</div>
      <div className="form" style={{ marginTop: 10 }}>
        <div className="field"><label>Sort by</label><div className="pills">{SORTS.map((x) => <button key={x} className={`pill ${sort === x ? 'on' : ''}`} onClick={() => setSort(x)}>{x}</button>)}</div></div>
        <div className="field"><label htmlFor="plq">Search free agents</label><input id="plq" type="text" value={q} placeholder="Search by name or team" onChange={(e) => setQ(e.target.value)} /></div>
        <label className="toggle"><input type="checkbox" checked={healthy} onChange={(e) => setHealthy(e.target.checked)} /> Only healthy, not on bye</label>
      </div>
      {d.hasTags && <div className="pills" style={{ marginBottom: 8 }}>{['Buy low', 'Sell high', 'Role growing'].map((x) => <button key={x} className={`pill ${tag === x ? 'on' : ''}`} onClick={() => setTag(tag === x ? '' : x)} title="From expected-points vs actual production (backtested: buy-low and sell-high predict the next game; role-growing is informational).">{x}</button>)}</div>}
      <div className="fresh" style={{ margin: '2px 0 8px' }}>{rows.length} players · rest-of-season points = expected fantasy points over the games left (byes, injuries and playoff weeks included), under your league scoring.</div>
      {rows.length === 0 ? <Empty title="No players match these filters" body="Try clearing a filter." /> : (
        <div ref={parent} className="list-virt" role="list" aria-label="Free agents">
          <div style={{ height: v.getTotalSize(), position: 'relative' }}>
            {v.getVirtualItems().map((it) => {
              const p = rows[it.index]
              return (
                <div key={p.id} data-index={it.index} ref={v.measureElement} style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${it.start}px)` }}>
                  <PlayerRow p={p} showActual={false} valuePct={100 * (p.ros || 0) / top} valueLabel={String(p.ros ?? 0)} whyOpen={false}
                    note={`${p.trend ? ' · trending' : ''}${p.owned >= 0 ? ` · ${Math.round(p.owned)}% owned` : ''}`} />
                </div>)
            })}
          </div>
        </div>)}
      <div className="fresh" style={{ marginTop: 6 }}><Icon n="info" /> Long lists are virtualized: only the rows on screen are drawn.</div>
    </>
  )
}
