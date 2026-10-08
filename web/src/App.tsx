import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { QueryClientProvider, useMutation } from '@tanstack/react-query'
import { clearPersisted, post, prefetch, put, qc, useApi } from './api'
import { ActionsCtx, BootCtx, Chip, FAvatar, Fresh, Icon, Modal, Notice, Skel, useActions } from './ui'
import { Markdown } from './md'
import { Shapes } from './fx'
import type { Boot } from './types'
import Overview from './pages/Overview'
import Team from './pages/Team'
import Matchup from './pages/Matchup'
import League from './pages/League'
import Players from './pages/Players'
import Assistant, { Msg } from './pages/Assistant'

const loadTrades = () => import('./pages/Trades')
const loadMore = () => import('./pages/More')
const loadSheet = () => import('./PlayerSheet')
const Trades = lazy(loadTrades), More = lazy(loadMore), PlayerSheet = lazy(loadSheet)

const NAV: [string, string, string, string[]][] = [
  ['/', 'Overview', 'home', ['/api/overview']], ['/team', 'My Team', 'sports_football', ['/api/team']], ['/matchup', 'Matchup', 'scoreboard', ['/api/matchup']],
  ['/players', 'Players', 'person_search', ['/api/players']], ['/trades', 'Trades', 'swap_horiz', ['/api/trades/meta']], ['/league', 'League', 'leaderboard', ['/api/league']],
  ['/assistant', 'Assistant', 'auto_awesome', ['/api/chat']], ['/more', 'More', 'more_horiz', ['/api/news']],
]
const PRELOAD = ['/api/overview', '/api/team', '/api/matchup', '/api/players', '/api/league', '/api/trades/meta']

function applyMode(mode: string) {
  const dark = mode === 'Dark' || (mode === 'System' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  try { localStorage.setItem('fh:mode', mode) } catch { /* ignore */ }
}

function Search({ boot }: { boot: Boot }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState(0)
  const { openPlayer } = useActions()
  const ref = useRef<HTMLInputElement>(null)
  const hits = useMemo(() => {
    const ql = q.trim().toLowerCase()
    if (!ql) return []
    return boot.search.filter((p) => p.name.toLowerCase().includes(ql) || p.team.toLowerCase() === ql).slice(0, 8)
  }, [q, boot.search])
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')
      if (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !typing)) { e.preventDefault(); ref.current?.focus() }
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [])
  const pick = (id: number) => { openPlayer(id); setQ(''); setOpen(false); ref.current?.blur() }
  const owner = (o: number) => (o === 0 ? 'free agent' : o === boot.me.id ? 'your team' : `on ${boot.teams.find((t) => t.id === o)?.first || 'a team'}`)
  return (
    <div className="search" role="combobox" aria-expanded={open && hits.length > 0} aria-haspopup="listbox">
      <Icon n="search" />
      <input ref={ref} value={q} placeholder="Search players   ( / )" aria-label="Search players" onChange={(e) => { setQ(e.target.value); setOpen(true); setSel(0) }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)) } else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) } else if (e.key === 'Enter' && hits[sel]) pick(hits[sel].id); else if (e.key === 'Escape') setOpen(false) }} />
      {open && hits.length > 0 && <div className="pop" role="listbox">{hits.map((p, i) => <button key={p.id} className={i === sel ? 'on' : ''} role="option" aria-selected={i === sel} onMouseDown={() => pick(p.id)}><b>{p.name}</b> {p.pos} · {p.team}<small>{owner(p.owner)}</small></button>)}</div>}
    </div>
  )
}

function Appearance({ boot }: { boot: Boot }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState(boot.settings.mode)
  const [accent, setAccent] = useState(boot.settings.accentTeam)
  const teams = Object.values(boot.nfl).sort((a, b) => a.name.localeCompare(b.name))
  return (
    <div style={{ position: 'relative' }}>
      <button className="btn icon" aria-label="Appearance" aria-expanded={open} onClick={() => setOpen(!open)}><Icon n="tune" /></button>
      {open && <div className="pop" style={{ left: 'auto', right: 0, width: 260, padding: 14 }}>
        <div className="field"><label>Theme</label><div className="pills">{['System', 'Light', 'Dark'].map((m) => <button key={m} className={`pill ${mode === m ? 'on' : ''}`} onClick={() => { setMode(m); applyMode(m); put('/api/settings', { mode: m }) }}>{m}</button>)}</div></div>
        <div className="field" style={{ marginTop: 12 }}><label>Accent team</label>
          <select value={accent} onChange={(e) => { setAccent(e.target.value); put('/api/settings', { accentTeam: e.target.value }).then(() => qc.invalidateQueries({ queryKey: ['/api/bootstrap'] })) }}>
            <option value="">None</option><option value="MY_TEAM">My fantasy team</option>{teams.map((t) => <option key={t.abbr} value={t.abbr}>{t.name}</option>)}</select></div>
      </div>}
    </div>
  )
}

function AISheet({ req, onClose }: { req: { prompt: string; title: string }; onClose: () => void }) {
  const run = useMutation({ mutationFn: () => post('/api/ai', { prompt: req.prompt }) })
  useEffect(() => { run.mutate() }, [])           // eslint-disable-line
  return (
    <Modal onClose={onClose} title={req.title}>
      <div className="fresh" style={{ marginBottom: 8 }}>{req.prompt}</div>
      {run.isPending && <><Skel n={2} h={60} /><span className="fresh">Looking at your league...</span></>}
      {run.error && <Notice kind="warn" icon="smart_toy">{(run.error as Error).message}</Notice>}
      {run.data && <Msg m={{ role: 'assistant', text: run.data.text, trace: run.data.trace }} />}
    </Modal>
  )
}

function Shell({ boot }: { boot: Boot }) {
  const [params, setParams] = useSearchParams()
  const [ai, setAi] = useState<{ prompt: string; title: string } | null>(null)
  const [toastMsg, setToast] = useState('')
  const [moreTab, setMoreTab] = useState('News')
  const [recents, setRecents] = useState<number[]>(() => { try { return JSON.parse(localStorage.getItem('fh:recents') || '[]') } catch { return [] } })
  const navigate = useNavigate()
  const section = useLocation().pathname.split('/')[1] || 'overview'
  const playerId = params.get('p') ? Number(params.get('p')) : null
  const openPlayer = useCallback((id: number) => {
    setParams((p) => { p.set('p', String(id)); return p })
    setRecents((r) => { const n = [id, ...r.filter((x) => x !== id)].slice(0, 6); try { localStorage.setItem('fh:recents', JSON.stringify(n)) } catch { /* ignore */ } return n })
  }, [setParams])
  const closePlayer = () => setParams((p) => { p.delete('p'); return p })
  const toast = useCallback((m: string) => { setToast(m); setTimeout(() => setToast(''), 2400) }, [])
  const actions = useMemo(() => ({ openPlayer, askAI: (prompt: string, title: string) => setAi({ prompt, title }), toast }), [openPlayer, toast])
  const refresh = useMutation({ mutationFn: () => post('/api/refresh'), onSuccess: () => { clearPersisted(); qc.invalidateQueries(); toast('Refreshed from ESPN') } })

  // warm every screen's data and code in the background so tab switches are instant
  useEffect(() => {
    const ric: any = (window as any).requestIdleCallback || ((f: () => void) => setTimeout(f, 300))
    ric(() => { PRELOAD.forEach((p, i) => setTimeout(() => prefetch(p), i * 120)); setTimeout(() => { loadTrades(); loadMore(); loadSheet(); prefetch('/api/chat', 0); prefetch('/api/strategy') }, 900) })
  }, [])
  useEffect(() => {                       // follow the OS in System mode
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const f = () => { if ((localStorage.getItem('fh:mode') || 'System') === 'System') applyMode('System') }
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [])
  useEffect(() => { applyMode(boot.settings.mode) }, [boot.settings.mode])
  useEffect(() => {
    const r = document.documentElement.style
    if (boot.accent) { r.setProperty('--accent', boot.accent); r.setProperty('--accent-ink', boot.accentInk || '#fff') } else { r.removeProperty('--accent'); r.removeProperty('--accent-ink') }
  }, [boot.accent, boot.accentInk])

  const L = boot.league
  return (
    <ActionsCtx.Provider value={actions}>
      <div className="wrap">
        <header className="top">
          <div className="brand"><div className="mark"><Icon n="sports_football" /></div><div><b>Fantasy Hub<Shapes /></b><small>{L.name} · {L.year}</small></div></div>
          <div className="grow" />
          <Search boot={boot} />
          <button className="btn" disabled={boot.demo || refresh.isPending} onClick={() => refresh.mutate()} title={boot.demo ? 'Demo data never changes.' : 'Fetch the latest from ESPN'}><Icon n="refresh" /> {refresh.isPending ? 'Refreshing' : 'Refresh'}</button>
          <Appearance boot={boot} />
        </header>
        <div className="ctxrow"><Chip kind="info" icon="calendar_month">Week {L.week}</Chip><span className="chip"><FAvatar t={boot.me} size={22} />{boot.me.name}</span><Chip icon="sports_score">{boot.me.record}</Chip>
          {boot.demo && <Chip kind="warn" icon="science">Demo data</Chip>}{!boot.demo && <Fresh age={boot.age} ttl={boot.ttl} />}</div>
        {recents.length > 0 && <div className="ctxrow" style={{ marginTop: 6 }}><span className="fresh">Recent</span>{recents.map((id) => { const s = boot.search.find((x) => x.id === id); return s ? <button key={id} className="pill" onClick={() => openPlayer(id)}><Icon n="history" /> {s.pos === 'D/ST' ? s.name.split(' ')[0] : s.name.split(' ').slice(-1)[0]}</button> : null })}</div>}
        <nav className="nav" aria-label="Main">{NAV.map(([to, label, ic, pre]) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')} onMouseEnter={() => pre.forEach((p) => prefetch(p))} onFocus={() => pre.forEach((p) => prefetch(p))}><Icon n={ic} /> {label}</NavLink>))}</nav>
        {boot.warnings.map((w, i) => <Notice key={i} kind="warn" icon="warning">{w}</Notice>)}
        <main data-s={section}>
          <Suspense fallback={<Skel n={4} h={80} />}>
            <Routes>
              <Route path="/" element={<Overview />} /><Route path="/team" element={<Team />} /><Route path="/matchup" element={<Matchup />} />
              <Route path="/players" element={<Players />} /><Route path="/trades" element={<Trades />} /><Route path="/league" element={<League />} />
              <Route path="/assistant" element={<Assistant />} /><Route path="/more" element={<More tab={moreTab} setTab={setMoreTab} />} />
              <Route path="*" element={<Notice icon="explore_off">That page doesn't exist. <button className="btn sm" onClick={() => navigate('/')}>Go to Overview</button></Notice>} />
            </Routes>
          </Suspense>
        </main>
        {boot.demo && <div className="actions" style={{ marginTop: 20 }}><button className="btn" onClick={async () => { await post('/api/demo', { on: false }); clearPersisted(); qc.invalidateQueries() }}><Icon n="logout" /> Exit demo</button></div>}
      </div>
      {playerId && <Suspense fallback={null}><PlayerSheet id={playerId} onClose={closePlayer} /></Suspense>}
      {ai && <AISheet req={ai} onClose={() => setAi(null)} />}
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
    </ActionsCtx.Provider>
  )
}

function Setup({ boot }: { boot: Boot }) {
  const s = boot.setup!
  return (
    <div className="wrap">
      <div className="brand"><div className="mark"><Icon n="sports_football" /></div><div><b>Fantasy Hub</b><small>Your weekly team manager</small></div></div>
      <div style={{ marginTop: 20 }} className="empty"><Icon n="link_off" /><b>{s.problem ? "Couldn't reach your league" : 'Connect your league'}</b>
        {s.problem || `Add ${(s.missing || []).join(', ')} to the .env file (see the README), then restart.`}</div>
      <div className="actions" style={{ marginTop: 14 }}>
        <button className="btn primary" onClick={async () => { await post('/api/demo', { on: true }); qc.invalidateQueries() }}><Icon n="science" /> Explore with demo data</button>
        <button className="btn" onClick={() => qc.invalidateQueries()}><Icon n="refresh" /> Try again</button></div>
    </div>
  )
}

function Gate() {
  const { data: boot, isLoading, error } = useApi<Boot>('/api/bootstrap', { stale: 60_000 })
  const seen = useRef(boot?.version)
  useEffect(() => { if (boot && seen.current !== undefined && boot.version !== seen.current) { clearPersisted(); qc.invalidateQueries() } seen.current = boot?.version }, [boot?.version])   // eslint-disable-line
  if (isLoading && !boot) return <div className="wrap"><Skel n={3} h={90} /></div>
  if (error && !boot) return <div className="wrap"><Notice kind="bad" icon="error">Can't reach the Fantasy Hub server. Start it with <code>make dev</code>. ({(error as Error).message})</Notice></div>
  if (!boot) return null
  return <BootCtx.Provider value={boot}>{boot.setup ? <Setup boot={boot} /> : <Shell boot={boot} />}</BootCtx.Provider>
}

export default function App() {
  return <QueryClientProvider client={qc}><BrowserRouter><Gate /></BrowserRouter></QueryClientProvider>
}
