const integer = new Intl.NumberFormat('pt-BR')
const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 })

export const fmtInt = (value: number) => integer.format(value)
export const fmtCompact = (value: number) => (Math.abs(value) < 10000 ? integer.format(value) : compact.format(value))

/** Milliseconds with precision that matches their magnitude. */
export function fmtMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const digits = value < 10 ? 2 : value < 100 ? 1 : 0
  return `${value.toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits })} ms`
}

export const fmtRatio = (value: number | null | undefined) =>
  value ? `${value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}×` : '—'

export const fmtPct = (part: number, whole: number) =>
  whole ? `${((100 * part) / whole).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%` : '0%'

const two = (n: number) => String(n).padStart(2, '0')
/** All times are UTC in this project; the UI says so explicitly. */
export function fmtUtc(iso: string, withSeconds = false): string {
  const d = new Date(iso)
  const base = `${two(d.getUTCDate())}/${two(d.getUTCMonth() + 1)} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`
  return withSeconds ? `${base}:${two(d.getUTCSeconds())}.${String(d.getUTCMilliseconds()).padStart(3, '0')}` : base
}
export const fmtDay = (iso: string) => {
  const d = new Date(iso)
  return `${two(d.getUTCDate())}/${two(d.getUTCMonth() + 1)}`
}

export function median(values: number[]): number | null {
  if (!values.length) return null
  const s = [...values].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

/** Clean axis ticks (1/2/5 x 10^k) from 0 to >= max. */
export function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0]
  const raw = max / count
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw
  const ticks: number[] = []
  for (let v = 0; v <= max + step * 0.999; v += step) ticks.push(Math.round(v))
  return ticks
}
