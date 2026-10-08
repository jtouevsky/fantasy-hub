import { ButtonHTMLAttributes, ReactNode, useRef } from 'react'
import { Icon } from './ui'

/** Circular progress ring (pure CSS conic-gradient + mask: no SVG filters, no JS animation). value is 0..1. */
export function Ring({ value, size = 72, children, label }: { value: number; size?: number; children?: ReactNode; label?: string }) {
  const v = Math.max(0, Math.min(1, value))
  return (
    <span className="ring-wrap" role="img" aria-label={label} style={{ '--s': `${size}px`, '--v': `${v * 360}deg` } as any}>
      <span className="ring" />
      <span className="ring-in">{children}</span>
    </span>
  )
}

/** Liquid-metal button: a chrome rim whose gradient angle turns on hover/press (CSS @property transition, nothing runs continuously). */
export function MetalButton({ icon, label, onClick, disabled, size = 64, type = 'button', title }: { icon: string; label?: string; onClick?: () => void; disabled?: boolean; size?: number; type?: ButtonHTMLAttributes<HTMLButtonElement>['type']; title?: string }) {
  return (
    <button className="metal" type={type} onClick={onClick} disabled={disabled} title={title || label} aria-label={label || title} style={{ '--s': `${size}px` } as any}>
      <span className="metal-core"><Icon n={icon} /></span>
      {label && <span className="metal-label">{label}</span>}
    </button>
  )
}

/** Glass orb for the assistant's identity (static gradients; it only brightens on hover). */
export function Orb({ size = 44 }: { size?: number }) {
  return <span className="orb" aria-hidden="true" style={{ '--s': `${size}px` } as any}><span /></span>
}

/** Split-flap number: each character sits on its own flap and flips only when that character actually changes. */
export function Flap({ text, label }: { text: string; label?: string }) {
  return (
    <span className="flap" role="img" aria-label={label || text}>
      {[...text].map((c, i) => (c === '.' || c === ' ' ? <span key={i} className="flap-dot">{c === '.' ? '.' : ''}</span> : <span key={`${i}${c}`} className="flap-c"><b>{c}</b></span>))}
    </span>
  )
}

/** Fluid illumination: a restrained light that follows the pointer while it is over the surface (updates a CSS variable, no animation loop). */
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

/** A few geometric accents (square, triangle, ring) so the all-circles language has some contrast. Decorative only. */
export function Shapes() {
  return <span className="shapes" aria-hidden="true"><i className="sq" /><i className="tri" /><i className="rg" /></span>
}
