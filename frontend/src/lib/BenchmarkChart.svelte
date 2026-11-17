<script lang="ts">
  import { SOURCE_LABEL, SOURCE_SHORT, SOURCES, type Operation, type Source } from './api'
  import { fmtMs, fmtRatio } from './format'

  let { operations }: { operations: Operation[] } = $props()

  let width = $state(760)
  const rowH = 60
  const m = { top: 6, right: 92, left: 12, bottom: 30 }
  const innerW = $derived(Math.max(120, width - m.left - m.right))
  const height = $derived(m.top + operations.length * rowH + m.bottom)

  const values = $derived(operations.flatMap((o) => SOURCES.flatMap((s) => o.sources[s].raw_http)).filter((v) => v > 0))
  const lo = $derived(10 ** Math.floor(Math.log10(Math.max(0.1, Math.min(...values)))))
  const hi = $derived(10 ** Math.ceil(Math.log10(Math.max(...values))))
  const x = (v: number) => m.left + ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * innerW
  // 1-2-5 ticks when there is room; decades only on narrow (phone) widths.
  const ticks = $derived((innerW < 420 ? [1] : [1, 2, 5]).flatMap((k) => {
    const out: number[] = []
    for (let p = lo; p <= hi; p *= 10) out.push(k * p)
    return out
  }).filter((t) => t >= lo && t <= hi).sort((a, b) => a - b))
  // Titles are SVG text (no wrapping): shorten to the available width (~6.6 px/char at 12.5 px).
  const fit = (text: string) => {
    const max = Math.floor((width - m.left - 4) / 6.6)
    return text.length > max ? `${text.slice(0, Math.max(8, max - 1))}…` : text
  }
  const color: Record<Source, string> = { postgresql: 'var(--db-pg)', cassandra: 'var(--db-cs)' }
  // Secondary encoding (the colour pair sits in the CVD warn band): circle = PostgreSQL, diamond = Cassandra.
  const diamond = (cx: number, cy: number, r: number) => `M${cx},${cy - r}L${cx + r},${cy}L${cx},${cy + r}L${cx - r},${cy}Z`
  // Deterministic vertical jitter so the 30 raw runs stay visible without randomness.
  const jitter = (i: number) => ((i * 37) % 9) - 4
</script>

<div class="bench-chart" bind:clientWidth={width}>
  <div class="legend" aria-hidden="true">
    <span><svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="var(--db-pg)" /></svg>PostgreSQL · mediana</span>
    <span><svg width="12" height="12"><path d={diamond(6, 6, 5.5)} fill="var(--db-cs)" /></svg>Cassandra · mediana</span>
    <span class="muted"><svg width="10" height="10"><circle cx="5" cy="5" r="2.2" fill="var(--muted)" /></svg>cada uma das 30 execuções</span>
  </div>
  <svg {width} {height} role="img" aria-label="Medianas de latência HTTP por operação, em escala logarítmica. Os valores completos estão na tabela abaixo.">
    {#each ticks as t (t)}
      <line class="grid" x1={x(t)} x2={x(t)} y1={m.top} y2={height - m.bottom} />
      <text class="tick" x={x(t)} y={height - 10} text-anchor="middle">{t < 1 ? t.toFixed(1) : t} ms</text>
    {/each}
    {#each operations as op, row (op.id)}
      {@const y0 = m.top + row * rowH}
      {@const yc = y0 + 40}
      {@const pg = op.sources.postgresql.http}
      {@const cs = op.sources.cassandra.http}
      {#if row > 0}<line class="sep" x1={m.left} x2={width} y1={y0 + 2} y2={y0 + 2} />{/if}
      <text class="title" x={m.left} y={y0 + 20}><tspan class="exp">{op.experiment}</tspan> {fit(op.title)}<title>{op.experiment} · {op.title}</title></text>
      {#if pg && cs}<line class="link" x1={x(pg.median)} x2={x(cs.median)} y1={yc} y2={yc} />{/if}
      {#each op.sources.postgresql.raw_http as v, i (i)}<circle cx={x(v)} cy={yc + jitter(i)} r="2.1" fill={color.postgresql} opacity=".32" />{/each}
      {#each op.sources.cassandra.raw_http as v, i (i)}<path d={diamond(x(v), yc + jitter(i), 2.6)} fill={color.cassandra} opacity=".32" />{/each}
      {#if pg}<circle cx={x(pg.median)} cy={yc} r="6.5" fill={color.postgresql} stroke="var(--card)" stroke-width="2"><title>{SOURCE_LABEL.postgresql}: mediana {fmtMs(pg.median)} (p25 {fmtMs(pg.p25)} – p75 {fmtMs(pg.p75)}, n={pg.n})</title></circle>{/if}
      {#if cs}<path d={diamond(x(cs.median), yc, 8)} fill={color.cassandra} stroke="var(--card)" stroke-width="2"><title>{SOURCE_LABEL.cassandra}: mediana {fmtMs(cs.median)} (p25 {fmtMs(cs.p25)} – p75 {fmtMs(cs.p75)}, n={cs.n})</title></path>{/if}
      {#if op.faster}
        <text class="ratio" x={width - m.right + 14} y={yc + 4}><tspan class="who">{SOURCE_SHORT[op.faster]}</tspan> {fmtRatio(op.ratio)}</text>
      {/if}
    {/each}
  </svg>
</div>

<style>
  .bench-chart { width: 100%; }
  svg { display: block; }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
  .legend span { display: inline-flex; gap: 7px; align-items: center; }
  .legend svg { display: inline; }
  .muted { color: var(--muted); }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .sep { stroke: var(--line-soft); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .title { fill: var(--text-2); font-size: 12.5px; }
  .exp { fill: var(--muted); font-family: var(--mono); font-size: 11px; }
  .link { stroke: var(--axis); stroke-width: 2; }
  .ratio { fill: var(--text); font-size: 13px; font-weight: 650; font-variant-numeric: tabular-nums; }
  .who { fill: var(--text-2); font-weight: 500; font-size: 11.5px; }
</style>
