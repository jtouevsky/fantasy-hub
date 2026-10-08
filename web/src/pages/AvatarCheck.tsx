import { useApi } from '../api'
import { Avatar, Skel } from '../ui'
import type { Player } from '../types'

/** Dev page (/dev/avatars): a contact sheet of real headshots at the sizes the app uses, to verify crops, fallbacks and consistency across players. */
export default function AvatarCheck() {
  const a = useApi<any>('/api/players'), b = useApi<any>('/api/team')
  if (!a.data || !b.data) return <Skel n={3} h={120} />
  const seen = new Set<number>()
  const ps: Player[] = [...b.data.current.map((r: any) => r.p).filter(Boolean), ...b.data.bench, ...a.data.fas].filter((p: Player) => (seen.has(p.id) ? false : (seen.add(p.id), true))).slice(0, 48)
  return (
    <div className="content-wrap" style={{ marginTop: 0 }}>
      <h2 className="panel-h">Avatar check: {ps.length} players</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 14 }}>
        {ps.map((p) => (
          <div key={p.id} className="card" style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}><Avatar p={p} size={36} /><Avatar p={p} size={44} /><Avatar p={p} size={72} /></div>
            <Avatar p={p} size={104} />
            <small>{p.name} · {p.pos}</small>
          </div>))}
      </div>
    </div>
  )
}
