import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { QueryClientProvider, useMutation } from '@tanstack/react-query'
import { clearPersisted, post, prefetch, qc, useApi } from './api'
import { ActionsCtx, BootCtx, Drawer, FAvatar, Fresh, Icon, Modal, Notice, Skel, Chip, useActions } from './ui'
import { Spinner } from './fx'
import type { Boot } from './types'
import Overview from './pages/Overview'
import Team from './pages/Team'
import Matchup from './pages/Matchup'
import League from './pages/League'
import Players from './pages/Players'
import Assistant, { Msg } from './pages/Assistant'
import Trades from './pages/Trades'
import More from './pages/More'
import PlayerSheet from './PlayerSheet'
import AvatarCheck from './pages/AvatarCheck'

const NAV: [string, string, string[], string][] = [
  ['/', 'Overview', ['/api/overview'], 'Your week at a glance'], ['/team', 'My team', ['/api/team'], 'Lineup, bench and injured reserve'], ['/matchup', 'Matchup', ['/api/matchup'], 'Head to head against your opponent'],
  ['/players', 'Players', ['/api/players'], 'Waivers and free agents'], ['/trades', 'Trades', ['/api/trades/meta'], 'Find, evaluate and track trade ideas'], ['/league', 'League', ['/api/league'], 'Standings and this week\'s slate'],
  ['/assistant', 'Assistant', ['/api/chat'], 'Ask anything about your team. Read-only.'], ['/more', 'More', ['/api/news'], 'News, strategy, report card and settings'],
]
const PRELOAD = ['/api/overview', '/api/team', '/api/matchup', '/api/players', '/api/league', '/api/trades/meta']

/** Search opens from a button, "/" or Cmd/Ctrl+K and closes on Esc or an outside click. Results are plain buttons, so everything is keyboard reachable. */
function Search({ boot }: { boot: Boot }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const { openPlayer } = useActions()
  const box = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const hits = useMemo(() => {
    const ql = q.trim().toLowerCase()
    if (!ql) return []
    return boot.search.filter((p) => p.name.toLowerCase().includes(ql) || p.team.toLowerCase() === ql).slice(0, 8)
  }, [q, boot.search])
  const close = useCallback(() => { setOpen(false); setQ(''); btn.current?.focus() }, [])
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
      if (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !typing)) { e.preventDefault(); setOpen(true) }
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [])
  useEffect(() => { if (open) input.current?.focus() }, [open])
  useEffect(() => {
    if (!open) return
    const d = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) { setOpen(false); setQ('') } }
    document.addEventListener('mousedown', d)
    return () => document.removeEventListener('mousedown', d)
  }, [open])
  const pick = (id: number) => { setOpen(false); setQ(''); openPlayer(id) }
  const owner = (o: number) => (o === 0 ? 'free agent' : o === boot.me.id ? 'your team' : `on ${boot.teams.find((t) => t.id === o)?.first || 'a team'}`)
  return (
    <div className="search" ref={box}>
      <button ref={btn} className="btn ghost" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}><Icon n="search" /> <span className="hide-xs">Search</span> <kbd className="hide-xs">/</kbd></button>
      {open && (
        <div className="search-pop" role="dialog" aria-label="Search players" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); close() } }}>
          <input ref={input} value={q} placeholder="Search players" aria-label="Search players" onChange={(e) => { setQ(e.target.value); setSel(0) }}
            onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)) } else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) } else if (e.key === 'Enter' && hits[sel]) pick(hits[sel].id) }} />
          <div className="results" role="listbox" aria-label="Results">
            {hits.map((p, i) => <button key={p.id} className={i === sel ? 'on' : ''} role="option" aria-selected={i === sel} onClick={() => pick(p.id)}><b>{p.name}</b> <span className="fresh">{p.pos} · {p.team}</span><small>{owner(p.owner)}</small></button>)}
            {q.trim() && hits.length === 0 && <div className="none">No players match "{q}".</div>}
          </div>
        </div>
      )}
    </div>
  )
}

/** One highlight glides between items (transform only). It is positioned from layout once per route change, never on pointer move. */
function Sidebar({ open, onClose, boot }: { open: boolean; onClose: () => void; boot: Boot }) {
  const nav = useRef<HTMLElement>(null)
  const loc = useLocation()
  useLayoutEffect(() => {
    const n = nav.current
    const a = n?.querySelector('a.on') as HTMLElement | null
    if (!n || !a) return
    n.style.setProperty('--gy', `${a.offsetTop}px`); n.style.setProperty('--gh', `${a.offsetHeight}px`)
    const r = requestAnimationFrame(() => n.classList.add('ready'))
    return () => cancelAnimationFrame(r)
  }, [loc.pathname])
  return (
    <>
      {open && <div className="scrim side-scrim" onMouseDown={onClose} role="presentation" />}
      <aside className={`side ${open ? 'open' : ''}`} aria-label="Navigation">
        <div className="side-h"><span>Menu</span><span>{NAV.length}</span></div>
        <nav className="nav" ref={nav} aria-label="Main"><span className="glide" aria-hidden="true" />
          {NAV.map(([to, label, pre]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')} onClick={onClose} onMouseEnter={() => pre.forEach((p) => prefetch(p))} onFocus={() => pre.forEach((p) => prefetch(p))}>{label}</NavLink>))}
        </nav>
        <div className="side-foot"><FAvatar t={boot.me} size={32} /><div><b>{boot.me.name}</b><small>{boot.me.record} · #{boot.me.standing}</small></div></div>
      </aside>
    </>
  )
}

function Shell({ boot }: { boot: Boot }) {
  const [params, setParams] = useSearchParams()
  const [ai, setAi] = useState<{ prompt: string; title: string } | null>(null)
  const [toastMsg, setToast] = useState('')
  const [menu, setMenu] = useState(false)
  const [moreTab, setMoreTab] = useState('News')
  const [recents, setRecents] = useState<number[]>(() => { try { return JSON.parse(localStorage.getItem('fh:recents') || '[]') } catch { return [] } })
  const timer = useRef<number>(0)
  const navigate = useNavigate()
  const loc = useLocation()
  const playerId = params.get('p') ? Number(params.get('p')) : null
  const openPlayer = useCallback((id: number) => {
    setParams((p) => { p.set('p', String(id)); return p })
    setRecents((r) => { const n = [id, ...r.filter((x) => x !== id)].slice(0, 6); try { localStorage.setItem('fh:recents', JSON.stringify(n)) } catch { /* ignore */ } return n })
  }, [setParams])
  const closePlayer = useCallback(() => setParams((p) => { p.delete('p'); return p }), [setParams])
  const toast = useCallback((m: string) => { window.clearTimeout(timer.current); setToast(m); timer.current = window.setTimeout(() => setToast(''), 2400) }, [])
  const actions = useMemo(() => ({ openPlayer, askAI: (prompt: string, title: string) => setAi({ prompt, title }), toast }), [openPlayer, toast])
  const refresh = useMutation({ mutationFn: () => post('/api/refresh'), onSuccess: () => { clearPersisted(); qc.invalidateQueries(); toast('Refreshed from ESPN') } })

  useEffect(() => {                         // warm every screen's data in the background so tab switches are instant
    const ric: any = (window as any).requestIdleCallback || ((f: () => void) => setTimeout(f, 300))
    ric(() => { PRELOAD.forEach((p, i) => setTimeout(() => prefetch(p), i * 120)); setTimeout(() => { prefetch('/api/chat', 0); prefetch('/api/strategy') }, 900) })
  }, [])
  useEffect(() => { setMenu(false) }, [loc.pathname])
  useEffect(() => { if (!menu) return; const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [menu])

  const L = boot.league
  const cur = NAV.find(([to]) => (to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to)))
  const title = cur ? cur[1] : loc.pathname.startsWith('/dev') ? 'Avatar check' : 'Not found'
  return (
    <ActionsCtx.Provider value={actions}>
      <header className="topbar">
        <button className="btn ghost icon menu-btn" aria-label="Open menu" aria-expanded={menu} onClick={() => setMenu(true)}><Icon n="menu" /></button>
        <div className="brand"><span className="mark shine"><Icon n="sports_football" /></span><b>Fantasy Hub</b></div>
        <div className="grow" />
        <button className={`btn ghost ${refresh.isPending ? 'busy' : ''}`} style={{ minWidth: 112 }} disabled={boot.demo || refresh.isPending} onClick={() => refresh.mutate()} title={boot.demo ? 'Demo data never changes.' : 'Fetch the latest from ESPN'}>
          {refresh.isPending ? <Spinner /> : <Icon n="refresh" />} <span className="hide-xs">Refresh</span></button>
        <Search boot={boot} />
      </header>
      <div className="shell">
        <Sidebar open={menu} onClose={() => setMenu(false)} boot={boot} />
        <main className="main" id="main">
          <div className="page" key={loc.pathname}>
            <div className="page-head">
              <h1>{title}</h1>
              <p>{cur ? cur[3] : ''}</p>
              <div className="page-meta"><Chip>Week {L.week}</Chip>{boot.demo && <Chip kind="warn" icon="science">Demo data</Chip>}{!boot.demo && <Fresh age={boot.age} ttl={boot.ttl} />}</div>
            </div>
            {recents.length > 0 && <div className="ctxrow recents"><span className="fresh">Recent</span>{recents.map((id) => { const s = boot.search.find((x) => x.id === id); return s ? <button key={id} className="pill" onClick={() => openPlayer(id)}>{s.pos === 'D/ST' ? s.name.split(' ')[0] : s.name.split(' ').slice(-1)[0]}</button> : null })}</div>}
            {boot.warnings.map((w, i) => <Notice key={i} kind="warn" icon="warning">{w}</Notice>)}
            <div className="content">
              <Suspense fallback={<Skel n={4} h={80} />}>
                <Routes>
                  <Route path="/" element={<Overview />} /><Route path="/team" element={<Team />} /><Route path="/matchup" element={<Matchup />} />
                  <Route path="/players" element={<Players />} /><Route path="/trades" element={<Trades />} /><Route path="/league" element={<League />} />
                  <Route path="/assistant" element={<Assistant />} /><Route path="/more" element={<More tab={moreTab} setTab={setMoreTab} />} />
                  <Route path="/dev/avatars" element={<AvatarCheck />} />
                  <Route path="*" element={<Notice icon="explore_off">That page doesn't exist. <button className="btn sm" onClick={() => navigate('/')}>Go to overview</button></Notice>} />
                </Routes>
              </Suspense>
            </div>
            {boot.demo && <div className="actions" style={{ marginTop: 24 }}><button className="btn" onClick={async () => { await post('/api/demo', { on: false }); clearPersisted(); qc.invalidateQueries() }}><Icon n="logout" /> Exit demo</button></div>}
          </div>
        </main>
      </div>
      {playerId && <Drawer onClose={closePlayer} title="Player"><PlayerSheet id={playerId} /></Drawer>}
      {ai && <AISheet req={ai} onClose={() => setAi(null)} />}
      <div aria-live="polite" role="status">{toastMsg && <div className="toast"><Icon n="check_circle" /> {toastMsg}</div>}</div>
    </ActionsCtx.Provider>
  )
}

function AISheet({ req, onClose }: { req: { prompt: string; title: string }; onClose: () => void }) {
  const run = useMutation({ mutationFn: () => post('/api/ai', { prompt: req.prompt }) })
  useEffect(() => { run.mutate() }, [])           // eslint-disable-line
  return (
    <Modal onClose={onClose} title={req.title}>
      <div className="fresh" style={{ marginBottom: 8 }}>{req.prompt}</div>
      {run.isPending && <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'wait' }}><Spinner /><span className="fresh">Looking at your league...</span></div>}
      {run.error && <Notice kind="warn" icon="smart_toy">{(run.error as Error).message}</Notice>}
      {run.data && <Msg m={{ role: 'assistant', text: run.data.text, trace: run.data.trace }} />}
    </Modal>
  )
}

function Setup({ boot }: { boot: Boot }) {
  const s = boot.setup!
  const [busy, setBusy] = useState(false)
  return (
    <div className="setup">
      <div className="tile shine"><Icon n="sports_football" /></div>
      <h1>{s.problem ? "Couldn't reach your league" : 'Connect your league'}</h1>
      <p>{s.problem || `Add ${(s.missing || []).join(', ')} to the .env file (see the README), then restart.`}</p>
      <div className="actions">
        <button className={`btn primary ${busy ? 'busy' : ''}`} style={{ minWidth: 200 }} disabled={busy} onClick={async () => { setBusy(true); await post('/api/demo', { on: true }); qc.invalidateQueries() }}>{busy ? <Spinner /> : <Icon n="science" />} Explore with demo data</button>
        <button className="btn" onClick={() => qc.invalidateQueries()}><Icon n="refresh" /> Try again</button>
      </div>
    </div>
  )
}

function Gate() {
  const { data: boot, isLoading, error } = useApi<Boot>('/api/bootstrap', { stale: 60_000 })
  const seen = useRef(boot?.version)
  useEffect(() => { if (boot && seen.current !== undefined && boot.version !== seen.current) { clearPersisted(); qc.invalidateQueries() } seen.current = boot?.version }, [boot?.version])   // eslint-disable-line
  if (isLoading && !boot) return <div className="setup"><Spinner /></div>
  if (error && !boot) return <div className="setup"><Notice kind="bad" icon="error">Can't reach the Fantasy Hub server. Start it with <code>make dev</code>. ({(error as Error).message})</Notice></div>
  if (!boot) return null
  return <BootCtx.Provider value={boot}>{boot.setup ? <Setup boot={boot} /> : <Shell boot={boot} />}</BootCtx.Provider>
}

export default function App() {
  return <QueryClientProvider client={qc}><BrowserRouter><Gate /></BrowserRouter></QueryClientProvider>
}
