<script lang="ts">
  import { ApiError, getOverview, getPage, queryPath, SOURCE_LABEL, SOURCES, type Source, type Timed } from './api'
  import { fmtMs, fmtRatio, median } from './format'

  let { from, to, category, severity }: { from: string; to: string; category: string | null; severity: number | null } = $props()

  type Mode = 'overview' | 'device' | 'alerts'
  const modes: { id: Mode; label: string; hint: string }[] = [
    { id: 'overview', label: 'Painel agregado', hint: 'Totais por hora, categoria e severidade com os filtros atuais (E4).' },
    { id: 'device', label: 'Q1 · dispositivo', hint: 'Primeira página (100) da linha do tempo de ids-sensor-06 (E2).' },
    { id: 'alerts', label: 'Q3 · alertas', hint: 'Primeira página (100) de alertas de severidade 3 (E3).' },
  ]
  let mode = $state<Mode>('overview')
  let repetitions = $state(5)
  let running = $state(false)
  let progress = $state(0)
  let error = $state<string | null>(null)
  type Acc = { http: number[]; db: number[]; body: string | null }
  let result = $state<{ mode: Mode; acc: Record<Source, Acc>; warm: Record<Source, number | null>; equal: boolean } | null>(null)

  function canonical(raw: string): string {
    const sort = (v: unknown): unknown => Array.isArray(v) ? v.map(sort)
      : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort((v as Record<string, unknown>)[k])])) : v
    return JSON.stringify(sort(JSON.parse(raw)))
  }

  function execute(source: Source): Promise<Timed<unknown>> {
    if (mode === 'overview') return getOverview(source, { from, to, category, severity })
    if (mode === 'device') return getPage(queryPath(source, 'device', 'ids-sensor-06', from, to, 100))
    return getPage(queryPath(source, 'alerts', '3', from, to, 100))
  }

  async function run() {
    running = true
    error = null
    progress = 0
    const acc: Record<Source, Acc> = { postgresql: { http: [], db: [], body: null }, cassandra: { http: [], db: [], body: null } }
    const warm: Record<Source, number | null> = { postgresql: null, cassandra: null }
    try {
      // Pair 0 is a discarded warm-up (connections, prepared statements, caches),
      // as in the benchmark protocol; then interleaved pairs with alternating order.
      for (let i = 0; i <= repetitions; i++) {
        for (const source of i % 2 ? SOURCES : [...SOURCES].reverse()) {
          const r = await execute(source)
          acc[source].body ??= canonical(r.raw)
          progress++
          if (i === 0) { warm[source] = r.httpMs; continue }
          acc[source].http.push(r.httpMs)
          if (r.dbMs !== null) acc[source].db.push(r.dbMs)
        }
      }
      result = { mode, acc, warm, equal: acc.postgresql.body === acc.cassandra.body }
    } catch (e) {
      error = e instanceof ApiError ? `${e.message} (${e.code})` : 'Falha inesperada na comparação.'
    } finally {
      running = false
    }
  }

  const summary = $derived(result ? SOURCES.map((s) => ({
    s, http: median(result!.acc[s].http)!, db: median(result!.acc[s].db), raw: result!.acc[s].http,
  })) : [])
  // Scale from the medians so a single slow run cannot flatten both bars;
  // runs beyond the scale are pinned to the end of the track (value on hover).
  const scale = $derived(Math.max(0.001, ...summary.map((r) => r.http)) * 1.6)
  const pos = (v: number) => Math.min(100, (v / scale) * 100)
  const fastest = $derived(summary.length ? [...summary].sort((a, b) => a.http - b.http)[0] : null)
  const slowest = $derived(summary.length ? [...summary].sort((a, b) => b.http - a.http)[0] : null)
</script>

<div class="live">
  <div class="controls">
    <div class="segmented" role="radiogroup" aria-label="Consulta a comparar">
      {#each modes as m}
        <button role="radio" aria-checked={mode === m.id} class:on={mode === m.id} disabled={running} onclick={() => (mode = m.id)}>{m.label}</button>
      {/each}
    </div>
    <label class="reps">Repetições
      <select bind:value={repetitions} disabled={running}><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option></select>
    </label>
    <button class="primary" onclick={run} disabled={running}>{running ? `Executando ${progress}/${(repetitions + 1) * 2}…` : 'Executar nos dois bancos'}</button>
  </div>
  <p class="hint">{modes.find((m) => m.id === mode)?.hint} Mesma requisição, mesmos parâmetros, ordem alternada.</p>

  {#if error}
    <p class="state error" role="alert">Comparação interrompida: {error}</p>
  {:else if !result}
    <p class="state">Nenhuma comparação executada nesta sessão. Os tempos aparecem aqui após a execução real.</p>
  {:else}
    <div class="rows" class:stale={running}>
      {#each summary as row (row.s)}
        <div class="row">
          <span class="name"><i class={row.s}></i>{SOURCE_LABEL[row.s]}</span>
          <span class="track">
            <span class="bar {row.s}" style:width={`${pos(row.http)}%`}></span>
            {#each row.raw as v}<span class="dot {row.s}" class:pinned={v > scale} style:left={`${pos(v)}%`} title={`${fmtMs(v)}${v > scale ? ' (fora da escala)' : ''}`}></span>{/each}
          </span>
          <span class="value"><strong>{fmtMs(row.http)}</strong><small>banco {fmtMs(row.db)}</small></span>
        </div>
      {/each}
    </div>
    <div class="verdict">
      {#if fastest && slowest && fastest.s !== slowest.s}
        <p><strong>{SOURCE_LABEL[fastest.s]}</strong> respondeu {fmtRatio(slowest.http / fastest.http)} mais rápido (mediana HTTP, {result.acc.postgresql.http.length} execuções por banco).</p>
      {/if}
      <p class={result.equal ? 'ok' : 'bad'}>{result.equal ? '✓ Resultado de negócio idêntico nos dois bancos' : '✗ Os bancos retornaram resultados diferentes'}</p>
    </div>
    <p class="note">Barra = mediana HTTP medida no navegador; pontos = cada execução (contorno claro = acima da escala); "banco" = Server-Timing da API (driver + banco). 1 par de aquecimento descartado (PG {fmtMs(result.warm.postgresql)}, CS {fmtMs(result.warm.cassandra)}). Observação ao vivo, não substitui o protocolo de benchmark.</p>
  {/if}
</div>

<style>
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .segmented { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; padding: 3px; gap: 2px; flex-wrap: wrap; }
  .segmented button { background: none; border: 0; color: var(--text-2); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  .segmented button.on { background: var(--surface-3); color: var(--text); }
  .reps { display: inline-flex; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); }
  .hint { color: var(--muted); font-size: 12px; margin: 10px 0 16px; }
  .rows { display: grid; gap: 14px; transition: opacity .2s; }
  .rows.stale { opacity: .45; }
  .row { display: grid; grid-template-columns: 110px 1fr 120px; gap: 12px; align-items: center; }
  .name { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
  .name i { width: 10px; height: 10px; border-radius: 2px; }
  .track { position: relative; height: 18px; display: flex; align-items: center; }
  .bar { height: 12px; border-radius: 0 4px 4px 0; min-width: 2px; opacity: .85; }
  .dot { position: absolute; width: 8px; height: 8px; border-radius: 50%; transform: translateX(-50%); border: 2px solid var(--surface); top: 1px; }
  .dot.pinned { transform: translateX(-100%); outline: 1px solid var(--text-2); }
  .postgresql { background: var(--db-pg); }
  .cassandra { background: var(--db-cs); }
  .value { display: grid; text-align: right; font-variant-numeric: tabular-nums; }
  .value strong { font-size: 14px; color: var(--text); }
  .value small { font-size: 11px; color: var(--muted); }
  .verdict { margin-top: 16px; display: grid; gap: 6px; font-size: 13px; }
  .verdict .ok { color: var(--good-text); }
  .verdict .bad { color: var(--critical-text); }
  .note { font-size: 11px; color: var(--muted); margin-top: 10px; }
  .state { color: var(--muted); font-size: 13px; padding: 18px 0; }
  .state.error { color: var(--critical-text); }
  @media (max-width: 560px) { .row { grid-template-columns: 1fr; gap: 6px; } .value { text-align: left; } }
</style>
