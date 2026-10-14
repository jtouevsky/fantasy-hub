import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './fonts.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)

// Pause ambient animation and hover transitions while scrolling so scroll frames only move layers.
let scrollTimer: number | undefined
addEventListener('scroll', () => {
  const root = document.documentElement
  if (!root.classList.contains('scrolling')) root.classList.add('scrolling')
  clearTimeout(scrollTimer)
  scrollTimer = window.setTimeout(() => root.classList.remove('scrolling'), 140)
}, { passive: true, capture: true })
