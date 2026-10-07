import { Fragment, ReactNode } from 'react'

// Minimal, safe markdown for assistant replies: headings, bold/italic/code, bullet and numbered lists, paragraphs. No raw HTML is ever injected.
function inline(s: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g
  let last = 0, m: RegExpExecArray | null, i = 0
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    const t = m[0]
    out.push(t.startsWith('**') ? <strong key={i++}>{t.slice(2, -2)}</strong> : t.startsWith('`') ? <code key={i++}>{t.slice(1, -1)}</code> : <em key={i++}>{t.slice(1, -1)}</em>)
    last = m.index + t.length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trim()) { i++; continue }
    const h = /^(#{1,4})\s+(.*)/.exec(l)
    if (h) { blocks.push(<h4 key={i} style={{ margin: '10px 0 4px' }}>{inline(h[2])}</h4>); i++; continue }
    if (/^\s*[-*]\s+/.test(l)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ''))
      blocks.push(<ul key={i}>{items.map((x, j) => <li key={j}>{inline(x)}</li>)}</ul>); continue
    }
    if (/^\s*\d+[.)]\s+/.test(l)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''))
      blocks.push(<ol key={i}>{items.map((x, j) => <li key={j}>{inline(x)}</li>)}</ol>); continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(\s*[-*]\s+|\s*\d+[.)]\s+|#{1,4}\s)/.test(lines[i])) para.push(lines[i++])
    blocks.push(<p key={i} style={{ margin: '6px 0' }}>{para.map((x, j) => <Fragment key={j}>{j > 0 && <br />}{inline(x)}</Fragment>)}</p>)
  }
  return <div className="t">{blocks}</div>
}
