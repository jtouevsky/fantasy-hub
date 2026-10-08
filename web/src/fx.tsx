import { ReactNode, useEffect, useRef, useState } from 'react'
import { Icon } from './ui'

/** Circular progress ring: a conic-gradient plus a mask. Label content sits above the masked layer. value is 0..1. */
export function Ring({ value, size = 72, children, label }: { value: number; size?: number; children?: ReactNode; label?: string }) {
  const v = Math.max(0, Math.min(1, value))
  return (
    <span className="ring-wrap" role="img" aria-label={label} style={{ '--s': `${size}px`, '--v': `${v * 360}deg` } as any}>
      <span className="ring" />
      <span className="ring-in">{children}</span>
    </span>
  )
}

/** Chunky pressable button with a hard offset shadow; springs on hover and sinks on press. `round` makes it a circle with a caption underneath. */
export function HeroButton({ icon, label, onClick, disabled, size = 56, type = 'button', title }: { icon: string; label?: string; onClick?: () => void; disabled?: boolean; size?: number; type?: 'button' | 'submit'; title?: string }) {
  return (
    <button className="hero" type={type} onClick={onClick} disabled={disabled} title={title || label} aria-label={label || title} style={{ '--s': `${size}px` } as any}>
      <span className="hero-core"><Icon n={icon} /></span>
      {label && <span className="hero-label">{label}</span>}
    </button>
  )
}

/** The assistant's character: a friendly blob with eyes. Static; the eyes track nothing and nothing loops. */
export function Mascot({ size = 56 }: { size?: number }) {
  return <span className="mascot" aria-hidden="true" style={{ '--s': `${size}px` } as any}><i /><i /><b /></span>
}

/** Number ticker: each digit is a column of 0-9 that slides (transform only) when the value changes. The first render never animates. */
export function Ticker({ value, className = '' }: { value: string; className?: string }) {
  return (
    <span className={`ticker ${className}`} role="img" aria-label={value}>
      {[...value].map((c, i) => (/\d/.test(c)
        ? <span key={i} className="tk-d" aria-hidden="true"><span className="tk-c" style={{ transform: `translateY(${-Number(c)}em)` }}>{'0123456789'.split('').map((d) => <span key={d}>{d}</span>)}</span></span>
        : <span key={i} className="tk-s" aria-hidden="true">{c}</span>))}
    </span>
  )
}

/** Tilted outlined sticker for status. Decorative: it never looks like a button. */
export function Sticker({ children, tone = '', tilt = -3, icon }: { children: ReactNode; tone?: string; tilt?: number; icon?: string }) {
  return <span className={`sticker ${tone}`} style={{ '--r': `${tilt}deg` } as any}>{icon && <Icon n={icon} />}{children}</span>
}

/** A short celebration: confetti pieces fall once (transform + opacity only), never block input, end on any click or Esc. Reduced motion shows just the banner. */
export function Celebrate({ title, sub, onDone }: { title: string; sub?: string; onDone: () => void }) {
  const [pieces] = useState(() => Array.from({ length: 22 }, (_, i) => ({ x: (i * 37) % 100, d: (i % 7) * 60, r: ((i * 53) % 360) - 180, c: i % 5, s: 6 + (i % 4) * 2 })))
  useEffect(() => {
    const t = setTimeout(onDone, 3200)
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onDone() }
    const c = () => onDone()
    window.addEventListener('keydown', k); window.addEventListener('pointerdown', c, { once: true })
    return () => { clearTimeout(t); window.removeEventListener('keydown', k); window.removeEventListener('pointerdown', c) }
  }, [onDone])
  return (
    <div className="celebrate" role="status" aria-live="polite">
      <div className="confetti" aria-hidden="true">{pieces.map((p, i) => <i key={i} className={`c${p.c}`} style={{ left: `${p.x}%`, animationDelay: `${p.d}ms`, '--r': `${p.r}deg`, width: p.s, height: p.s * 1.6 } as any} />)}</div>
      <div className="cel-card"><Sticker tone="lime" tilt={-4} icon="emoji_events">{title}</Sticker>{sub && <div className="cel-sub">{sub}</div>}</div>
    </div>
  )
}

/** Fires once per key (remembered in localStorage) so a celebration never repeats. */
export function useOnce(key: string): [boolean, () => void] {
  const [show, setShow] = useState(false)
  const done = useRef(false)
  useEffect(() => {
    try { if (!localStorage.getItem(key)) setShow(true) } catch { /* ignore */ }
  }, [key])
  const finish = () => { if (done.current) return; done.current = true; setShow(false); try { localStorage.setItem(key, '1') } catch { /* ignore */ } }
  return [show, finish]
}

/** Small decorative geometry (square, triangle, ring) used as section markers. */
export function Shapes() {
  return <span className="shapes" aria-hidden="true"><i className="sq" /><i className="tri" /><i className="rg" /></span>
}

/** Fluid pointer light for hero plates: updates two CSS variables while hovering; no animation loop. */
export function useIllumination() {
  const ref = useRef<HTMLElement>(null)
  const raf = useRef(0)
  const onMove = (e: React.PointerEvent) => {
    const el = ref.current
    if (!el || raf.current) return
    raf.current = requestAnimationFrame(() => {
      raf.current = 0
      const r = el.getBoundingClientRect()
      el.style.setProperty('--mx', `${((e.clientX - r.left) / r.width) * 100}%`)
      el.style.setProperty('--my', `${((e.clientY - r.top) / r.height) * 100}%`)
    })
  }
  return { ref, onPointerMove: onMove }
}
