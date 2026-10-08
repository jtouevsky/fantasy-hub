export interface Player {
  id: number; name: string; pos: string; team: string; slot: string; status: string; statusLabel: string; onBye: boolean; out: boolean; risky: boolean
  proj: number; espnProj: number; hasEdge: boolean; edgeTotal: number; actualPpg: number; weekPts: number; totalPts: number; gp: number
  opp: string; kick: string; lock: string; owner: number | null; owned: number; watch: boolean; color: string; tags: [string, string][]; bye: number | null
  img: { s: string; m: string } | null; edge?: any[]; context?: any[]; edgeRos?: number
  ros?: number; key?: number; trend?: number; healthy?: boolean; where?: string; tl?: string | null
  st?: { ppg: number; raw: number; tdShare: number; touches: number; snap: number | null; dep: boolean; vol: boolean; fmc: [number, number, number] } & Record<string, any>
}
export interface FTeam { id: number; name: string; abbrev: string; owner: string; first: string; record: string; standing: number; pf: number; pa: number; playoffPct: number; color: string; logo: string | null; me: boolean }
export interface NflTeam { abbr: string; name: string; short: string; color: string; logo: string; dx: number; dy: number; k: number }
export interface Boot {
  demo: boolean; settings: { mode: string; accentTeam: string }; nfl: Record<string, NflTeam>
  setup?: { missing?: string[]; problem?: string }
  league: { name: string; year: number; week: number; finalWeek: number; regWeeks: number; teamCount: number; slots: Record<string, number>; bench: number; ir: number; faab: number; waiverDays: string[]; scoring: Record<string, number> }
  me: FTeam; teams: FTeam[]; warnings: string[]; age: number | null; ttl: number; accent: string | null; accentInk: string | null; scanStatus: string; edgeOn: boolean; version: number
  search: { id: number; name: string; pos: string; team: string; owner: number }[]
}
