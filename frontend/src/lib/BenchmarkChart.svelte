<script lang="ts">
  import { SOURCE_LABEL, SOURCES, type Operation, type Source } from './api'
  import { fmtMs, fmtRatio } from './format'

  let { operations }: { operations: Operation[] } = $props()

  let width = $state(760)
  const rowH = 58
  const m = { top: 8, right: 110, left: 12, bottom: 30 }
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
  // Titles are SVG text (no wrapping): shorten to the available width (~6.4 px/char at 12 px).
  const fit = (text: string) => {
    const max = Math.floor((width - m.left - 4) / 6.4)
    return text.length > max ? `${text.slice(0, Math.max(8, max - 1))}…` : text
  }
  const color: Record<Source, string> = { postgresql: 'var(--db-pg)', cassandra: 'var(--db-cs)' }
  // Deterministic vertical jitter so the 30 raw runs stay visible without randomness.
  const jitter = (i: number) => ((i * 37) % 9) - 4
</script>

<div class="bench-chart" bind:clientWidth={width}>
  <div class="legend" aria-hidden="true">
    {#each SOURCES as s}<span><i style:background={color[s]}></i>{SOURCE_LABEL[s]} · mediana</span>{/each}
    <span class="muted"><i class="faint"></i>cada execução medida</span>
  </div>
  <svg {width} {height} role="img" aria-label="Medianas de latência HTTP por operação, escala logarítmica. Valores completos na tabela abaixo.">
    {#each ticks as t}
      <line class="grid" x1={x(t)} x2={x(t)} y1={m.top} y2={height - m.bottom} />
      <text class="tick" x={x(t)} y={height - 10} text-anchor="middle">{t < 1 ? t.toFixed(1) : t} ms</text>
    {/each}
    {#each operations as op, row (op.id)}
      {@const y0 = m.top + row * rowH}
      {@const yc = y0 + 38}
      {@const pg = op.sources.postgresql.http}
      {@const cs = op.sources.cassandra.http}
      <text class="title" x={m.left} y={y0 + 16}>{fit(`${op.experiment} · ${op.title}`)}<title>{op.experiment} · {op.title}</title></text>
      {#if pg && cs}
        <line class="link" x1={x(pg.median)} x2={x(cs.median)} y1={yc} y2={yc} />
      {/if}
      {#each SOURCES as s}
        {#each op.sources[s].raw_http as v, i}
          <circle cx={x(v)} cy={yc + jitter(i)} r="2.2" fill={color[s]} opacity=".35" />
        {/each}
      {/each}
      {#each SOURCES as s}
        {@const st = op.sources[s].http}
        {#if st}
          <circle cx={x(st.median)} cy={yc} r="6" fill={color[s]} stroke="var(--surface)" stroke-width="2">
            <title>{SOURCE_LABEL[s]}: mediana {fmtMs(st.median)} (p25 {fmtMs(st.p25)} – p75 {fmtMs(st.p75)}, n={st.n})</title>
          </circle>
        {/if}
      {/each}
      {#if op.faster}
        <circle cx={width - m.right + 16} cy={yc} r="4" fill={color[op.faster]} />
        <text class="ratio" x={width - m.right + 26} y={yc + 4}>{fmtRatio(op.ratio)}</text>
      {/if}
    {/each}
  </svg>
</div>

<style>
  .bench-chart { width: 100%; }
  svg { display: block; }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--text-2); margin-bottom: 6px; }
  .legend span { display: inline-flex; gap: 7px; align-items: center; }
  .legend i { width: 10px; height: 10px; border-radius: 50%; }
  .legend i.faint { background: var(--muted); opacity: .45; width: 5px; height: 5px; }
  .muted { color: var(--muted); }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .title { fill: var(--text-2); font-size: 12px; }
  .link { stroke: var(--axis); stroke-width: 2; }
  .ratio { fill: var(--text); font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
