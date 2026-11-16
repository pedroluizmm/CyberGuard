<script lang="ts">
  import { CATEGORIES, CATEGORY_LABEL, type Category, type Point } from './api'
  import { fmtCompact, fmtDay, fmtInt, fmtUtc, niceTicks } from './format'

  let { points, visible }: { points: Point[]; visible: Category[] } = $props()

  const color: Record<Category, string> = { authentication: 'var(--cat-auth)', network: 'var(--cat-net)', alert: 'var(--cat-alert)' }
  const height = 260
  const m = { top: 14, right: 18, bottom: 30, left: 52 }
  let width = $state(720)
  let hover = $state<number | null>(null)
  let svg: SVGSVGElement | undefined = $state()

  const innerW = $derived(Math.max(40, width - m.left - m.right))
  const innerH = height - m.top - m.bottom
  const index = (c: Category) => CATEGORIES.indexOf(c)
  const peak = $derived(Math.max(1, ...points.flatMap((p) => visible.map((c) => p.by_category[index(c)]))))
  const ticks = $derived(niceTicks(peak))
  const top = $derived(ticks[ticks.length - 1] || 1)
  const x = (i: number) => m.left + (points.length <= 1 ? innerW / 2 : (i * innerW) / (points.length - 1))
  const y = (v: number) => m.top + innerH - (v / top) * innerH
  const lines = $derived(visible.map((c) => ({
    c, d: points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.by_category[index(c)]).toFixed(1)}`).join(''),
  })))
  // Midnight ticks for multi-day windows, every 3 h for a single day.
  const xTicks = $derived.by(() => {
    const candidates = points.map((p, i) => ({ p, i })).filter(({ p }) => {
      const h = new Date(p.t).getUTCHours()
      return points.length > 48 ? h === 0 : h % 3 === 0
    })
    // Keep at least ~52 px between labels (phone widths): show every k-th tick.
    const spacing = candidates.length > 1 ? x(candidates[1].i) - x(candidates[0].i) : Infinity
    const every = Math.max(1, Math.ceil(52 / spacing))
    return candidates.filter((_, k) => k % every === 0)
  })
  const xLabel = (iso: string) => (points.length > 48 ? fmtDay(iso) : `${String(new Date(iso).getUTCHours()).padStart(2, '0')}h`)

  function pick(event: PointerEvent) {
    if (!svg || points.length === 0) return
    const rect = svg.getBoundingClientRect()
    const ratio = (event.clientX - rect.left - m.left) / innerW
    hover = Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))))
  }
  function key(event: KeyboardEvent) {
    if (!points.length) return
    const current = hover ?? points.length - 1
    if (event.key === 'ArrowLeft') hover = Math.max(0, current - 1)
    else if (event.key === 'ArrowRight') hover = Math.min(points.length - 1, current + 1)
    else if (event.key === 'Home') hover = 0
    else if (event.key === 'End') hover = points.length - 1
    else return
    event.preventDefault()
  }
  const active = $derived(hover === null ? null : points[hover])
  const tipLeft = $derived(hover === null ? 0 : x(hover))
</script>

<div class="chart" bind:clientWidth={width}>
  <div class="legend" aria-hidden="true">
    {#each visible as c}<span><i style:background={color[c]}></i>{CATEGORY_LABEL[c]}</span>{/each}
  </div>
  <svg bind:this={svg} {width} {height} role="slider" tabindex="0"
    aria-label={`Eventos por hora (UTC), ${points.length} horas. Use as setas para percorrer.`}
    aria-valuemin={0} aria-valuemax={Math.max(0, points.length - 1)} aria-valuenow={hover ?? 0}
    aria-valuetext={active ? `${fmtUtc(active.t)} UTC: ${visible.map((c) => `${CATEGORY_LABEL[c]} ${fmtInt(active.by_category[index(c)])}`).join(', ')}` : 'Nenhuma hora selecionada'}
    onpointermove={pick} onpointerleave={() => (hover = null)} onkeydown={key}
    onfocus={() => (hover = hover ?? points.length - 1)} onblur={() => (hover = null)}>
    {#each ticks as t}
      <line class="grid" x1={m.left} x2={m.left + innerW} y1={y(t)} y2={y(t)} />
      <text class="tick" x={m.left - 8} y={y(t)} text-anchor="end" dominant-baseline="middle">{fmtCompact(t)}</text>
    {/each}
    <line class="axis" x1={m.left} x2={m.left + innerW} y1={m.top + innerH} y2={m.top + innerH} />
    {#each xTicks as { p, i }}
      <text class="tick" x={x(i)} y={height - 8} text-anchor="middle">{xLabel(p.t)}</text>
    {/each}
    {#each lines as line (line.c)}
      <path d={line.d} fill="none" stroke={color[line.c]} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
    {/each}
    {#if active && hover !== null}
      <line class="crosshair" x1={x(hover)} x2={x(hover)} y1={m.top} y2={m.top + innerH} />
      {#each visible as c}
        <circle cx={x(hover)} cy={y(active.by_category[index(c)])} r="4.5" fill={color[c]} stroke="var(--surface)" stroke-width="2" />
      {/each}
    {/if}
  </svg>
  {#if active}
    <div class="tooltip" class:flip={tipLeft > width * 0.62} style:left={`${tipLeft}px`} role="status">
      <p class="tip-title">{fmtUtc(active.t)} UTC</p>
      {#each visible as c}
        <p><i style:background={color[c]}></i><strong>{fmtInt(active.by_category[index(c)])}</strong><span>{CATEGORY_LABEL[c]}</span></p>
      {/each}
      {#if visible.length > 1}<p class="tip-total"><strong>{fmtInt(active.total)}</strong><span>total na hora</span></p>{/if}
    </div>
  {/if}
</div>

<style>
  .chart { position: relative; width: 100%; }
  svg { display: block; overflow: visible; touch-action: pan-y; }
  svg:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; border-radius: 4px; }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; }
  .legend i, .tooltip i { width: 14px; height: 2px; border-radius: 2px; display: inline-block; }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--axis); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .crosshair { stroke: var(--text-2); stroke-width: 1; opacity: .5; }
  .tooltip { position: absolute; top: 30px; transform: translateX(14px); background: var(--surface-3); border: 1px solid var(--line-strong);
    border-radius: 8px; padding: 9px 11px; min-width: 150px; pointer-events: none; box-shadow: 0 8px 24px #0007; z-index: 2; }
  .tooltip.flip { transform: translateX(calc(-100% - 14px)); }
  .tooltip p { display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 3px 0; }
  .tooltip strong { font-variant-numeric: tabular-nums; color: var(--text); min-width: 46px; }
  .tooltip span { color: var(--text-2); }
  .tip-title { color: var(--muted) !important; font-size: 11px !important; margin-bottom: 6px !important; }
  .tip-total { border-top: 1px solid var(--line); padding-top: 5px; margin-top: 6px !important; }
</style>
