<script lang="ts">
  import { SOURCE_LABEL, SOURCES, type ScaleOperation, type Source } from './api'
  import { fmtDelta, fmtEvents, fmtMs, fmtRatio } from './format'

  /** 0..>=max in 1/2/2.5/5 x 10^k steps, keeping decimals for sub-millisecond scales. */
  function niceTicks(max: number, count: number): number[] {
    if (!(max > 0)) return [0, 1]
    const raw = max / count
    const power = 10 ** Math.floor(Math.log10(raw))
    const step = [1, 2, 2.5, 5, 10].map((k) => k * power).find((s) => s >= raw) ?? raw
    const digits = Math.max(0, -Math.floor(Math.log10(step)) + 1)
    const out: number[] = []
    for (let v = 0; v <= max + step * 0.999; v += step) out.push(Number(v.toFixed(digits)))
    return out
  }

  // Median HTTP latency of one operation at each measured dataset size (whiskers: p25–p75).
  // Linear axes from zero, so growth is read directly; every value is also in the table below.
  let { op }: { op: ScaleOperation } = $props()

  let width = $state(260)
  const height = 150
  const m = { top: 10, right: 12, bottom: 24, left: 40 }
  const pts = $derived(op.points)
  const maxSize = $derived(Math.max(...pts.map((p) => p.logical_events)))
  const maxMs = $derived(Math.max(...pts.flatMap((p) => SOURCES.map((s) => p[s].http.p75 ?? p[s].http.median ?? 0))))
  const ticks = $derived(niceTicks(maxMs * 1.05, 3))
  const top = $derived(ticks[ticks.length - 1] || 1)
  const x = (n: number) => m.left + (n / maxSize) * (width - m.left - m.right)
  const y = (v: number) => height - m.bottom - (v / top) * (height - m.top - m.bottom)
  const color: Record<Source, string> = { postgresql: 'var(--db-pg)', cassandra: 'var(--db-cs)' }
  const diamond = (cx: number, cy: number, r: number) => `M${cx},${cy - r}L${cx + r},${cy}L${cx},${cy + r}L${cx - r},${cy}Z`
  const line = (s: Source) => pts.filter((p) => p[s].http.median != null)
    .map((p, i) => `${i ? 'L' : 'M'}${x(p.logical_events).toFixed(1)},${y(p[s].http.median!).toFixed(1)}`).join('')
  const first = $derived(pts[0])
  const last = $derived(pts[pts.length - 1])
  const label = $derived(`${op.experiment} ${op.title}: ` + SOURCES.map((s) =>
    `${SOURCE_LABEL[s]} de ${fmtMs(first[s].http.median)} em ${fmtEvents(first.logical_events)} para ${fmtMs(last[s].http.median)} em ${fmtEvents(last.logical_events)}`).join('; '))
</script>

<figure class="tile">
  <figcaption><span class="exp">{op.experiment}</span> {op.title}</figcaption>
  <div class="plot" bind:clientWidth={width}>
    <svg {width} {height} role="img" aria-label={label}>
      {#each ticks as t (t)}
        <line class="grid" x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} />
        <text class="tick" x={m.left - 6} y={y(t) + 3.5} text-anchor="end">{t.toLocaleString('pt-BR')}</text>
      {/each}
      {#each pts as p (p.logical_events)}
        <text class="tick" x={x(p.logical_events)} y={height - 7} text-anchor="middle">{fmtEvents(p.logical_events)}</text>
      {/each}
      {#each SOURCES as s (s)}
        <path d={line(s)} fill="none" stroke={color[s]} stroke-width="2" stroke-linejoin="round" />
        {#each pts as p (p.logical_events)}
          {@const h = p[s].http}
          {#if h.median != null}
            {#if h.p25 != null && h.p75 != null}<line x1={x(p.logical_events)} x2={x(p.logical_events)} y1={y(h.p25)} y2={y(h.p75)} stroke={color[s]} stroke-width="5" stroke-linecap="round" opacity=".28" />{/if}
            {#if s === 'postgresql'}
              <circle cx={x(p.logical_events)} cy={y(h.median)} r="4.2" fill={color[s]} stroke="var(--card)" stroke-width="1.5"><title>{SOURCE_LABEL[s]} · {fmtEvents(p.logical_events)}: {fmtMs(h.median)}</title></circle>
            {:else}
              <path d={diamond(x(p.logical_events), y(h.median), 5.4)} fill={color[s]} stroke="var(--card)" stroke-width="1.5"><title>{SOURCE_LABEL[s]} · {fmtEvents(p.logical_events)}: {fmtMs(h.median)}</title></path>
            {/if}
          {/if}
        {/each}
      {/each}
    </svg>
  </div>
  <p class="foot">
    <span><i class="dot pg"></i>{fmtDelta(first.postgresql.http.median, last.postgresql.http.median)}</span>
    <span><i class="dot cs"></i>{fmtDelta(first.cassandra.http.median, last.cassandra.http.median)}</span>
    {#if last.faster}<span class="who">{fmtEvents(last.logical_events)}: {SOURCE_LABEL[last.faster]} {fmtRatio(last.ratio)}</span>{/if}
  </p>
</figure>

<style>
  .tile { margin: 0; display: grid; gap: 6px; padding: 12px 12px 10px; border: 1px solid var(--line-soft); border-radius: 12px; background: var(--sidebar); min-width: 0; }
  figcaption { font-size: 12px; color: var(--text-2); line-height: 1.35; min-height: 2.7em; }
  .exp { font-family: var(--mono); font-size: 10.5px; color: var(--muted); margin-right: 3px; }
  .plot { width: 100%; }
  svg { display: block; overflow: visible; }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 10.5px; font-variant-numeric: tabular-nums; }
  .foot { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .foot span { display: inline-flex; align-items: center; gap: 5px; }
  .dot { width: 8px; height: 8px; display: inline-block; }
  .dot.pg { border-radius: 50%; background: var(--db-pg); }
  .dot.cs { background: var(--db-cs); transform: rotate(45deg) scale(0.85); }
  .who { margin-left: auto; color: var(--text); font-weight: 600; }
</style>
