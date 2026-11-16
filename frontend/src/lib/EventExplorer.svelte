<script lang="ts">
  import { ApiError, CATEGORY_LABEL, getPage, queryPath, SEVERITY_LABEL, SOURCE_LABEL, type EventPage, type QueryKind, type Source } from './api'
  import { fmtMs, fmtUtc } from './format'

  let { source, from, to }: { source: Source; from: string; to: string } = $props()

  const kinds: { id: QueryKind; label: string; field: string; placeholder: string; examples: string[] }[] = [
    { id: 'device', label: 'Q1 · Dispositivo', field: 'device_id', placeholder: 'ex.: ids-sensor-06', examples: ['ids-sensor-06', 'vpn-gw-01', 'fw-edge-03'] },
    { id: 'ip', label: 'Q2 · IP de origem', field: 'source_ip', placeholder: 'ex.: 2001:db8:bad:4::6', examples: ['2001:db8:bad:4::6', '203.0.113.173', '2001:db8:bad:3::16'] },
    { id: 'alerts', label: 'Q3 · Alertas por severidade', field: 'severity', placeholder: '1 a 5', examples: ['5', '4', '3'] },
  ]
  let kind = $state<QueryKind>('device')
  let value = $state('ids-sensor-06')
  let pageSize = $state(25)
  let cursors = $state<(string | null)[]>([null])
  let status = $state<'idle' | 'loading' | 'ready' | 'error'>('idle')
  let page = $state<EventPage | null>(null)
  let timing = $state<{ http: number; db: number | null; source: Source } | null>(null)
  let error = $state<{ kind: string; message: string } | null>(null)

  const spec = $derived(kinds.find((k) => k.id === kind)!)
  const valid = $derived(kind === 'alerts' ? /^[1-5]$/.test(value.trim()) : value.trim().length > 0)

  function choose(next: QueryKind) {
    kind = next
    value = kinds.find((k) => k.id === next)!.examples[0]
    page = null
    status = 'idle'
  }

  async function load(position: number) {
    if (!valid) return
    status = 'loading'
    error = null
    const querySource = source
    try {
      const result = await getPage(queryPath(querySource, kind, value.trim(), from, to, pageSize, cursors[position]))
      page = result.data
      timing = { http: result.httpMs, db: result.dbMs, source: querySource }
      cursors = [...cursors.slice(0, position + 1), result.data.next_cursor]
      current = position
      status = 'ready'
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('contract', 'unknown', 'Falha inesperada.')
      error = {
        kind: err.kind,
        message: err.kind === 'invalid' ? `Parâmetros rejeitados pela API: ${err.message}`
          : err.kind === 'unavailable' || err.kind === 'network' ? `${SOURCE_LABEL[querySource]} indisponível: ${err.message}` : err.message,
      }
      status = 'error'
    }
  }
  let current = $state(0)

  function submit(event: SubmitEvent) {
    event.preventDefault()
    cursors = [null]
    void load(0)
  }

  // The selected source or period changed: the shown page no longer matches; re-run.
  let lastKey = ''
  $effect(() => {
    const key = `${source}|${from}|${to}`
    if (lastKey && key !== lastKey && status !== 'idle') {
      cursors = [null]
      void load(0)
    }
    lastKey = key
  })
</script>

<div class="explorer">
  <form onsubmit={submit} class="form">
    <div class="segmented" role="radiogroup" aria-label="Padrão de consulta">
      {#each kinds as k}<button type="button" role="radio" aria-checked={kind === k.id} class:on={kind === k.id} onclick={() => choose(k.id)}>{k.label}</button>{/each}
    </div>
    <label class="field"><span>{spec.field}</span>
      <input bind:value placeholder={spec.placeholder} autocomplete="off" spellcheck="false" aria-invalid={!valid} />
    </label>
    <label class="field small"><span>página</span>
      <select bind:value={pageSize}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select>
    </label>
    <button class="primary" type="submit" disabled={!valid || status === 'loading'}>{status === 'loading' ? 'Consultando…' : 'Consultar'}</button>
  </form>
  <div class="examples">Maiores partições da massa (manifesto):
    {#each spec.examples as ex}<button type="button" class="chip" onclick={() => { value = ex; cursors = [null]; void load(0) }}>{ex}</button>{/each}
  </div>

  {#if status === 'idle'}
    <p class="state">Escolha o padrão de consulta e execute. Cada página é uma consulta real no banco selecionado ({SOURCE_LABEL[source]}).</p>
  {:else if status === 'error' && error}
    <p class="state error" role="alert">{error.message}</p>
  {:else if page}
    <div class="meta" aria-live="polite">
      <span>{page.items.length} eventos nesta página · página {current + 1}</span>
      {#if timing}<span class="timing">{SOURCE_LABEL[timing.source]} · HTTP {fmtMs(timing.http)} · banco {fmtMs(timing.db)}</span>{/if}
    </div>
    {#if page.items.length === 0}
      <p class="state">Nenhum evento encontrado para {spec.field} = {value} no período selecionado.</p>
    {:else}
      <div class="table-wrap" class:stale={status === 'loading'}>
        <table>
          <thead><tr><th>Ocorrência (UTC)</th><th>Dispositivo</th><th>IP de origem</th><th>Categoria / tipo</th><th>Sev.</th><th>Resultado</th><th>Mensagem</th></tr></thead>
          <tbody>
            {#each page.items as item (item.data.event_id)}
              <tr>
                <td class="mono">{fmtUtc(item.data.occurred_at, true)}</td>
                <td class="mono">{item.data.device_id}</td>
                <td class="mono">{item.data.source_ip}</td>
                <td>{CATEGORY_LABEL[item.data.category]}<small>{item.data.event_type}</small></td>
                <td><span class="sev" class:light={item.data.severity >= 3} style:--c={`var(--sev-${item.data.severity})`} title={SEVERITY_LABEL[item.data.severity - 1]}>{item.data.severity}</span></td>
                <td>{item.data.outcome}</td>
                <td class="msg" title={item.data.message}>{item.data.message}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    <div class="pager">
      <button class="ghost" disabled={current === 0 || status === 'loading'} onclick={() => load(current - 1)}>← Anterior</button>
      <button class="ghost" disabled={!page.next_cursor || status === 'loading'} onclick={() => load(current + 1)}>Próxima →</button>
      <span class="muted">Paginação por cursor (keyset), sem OFFSET.</span>
    </div>
  {/if}
</div>

<style>
  .form { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
  .segmented { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; padding: 3px; gap: 2px; flex-wrap: wrap; }
  .segmented button { background: none; border: 0; color: var(--text-2); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  .segmented button.on { background: var(--surface-3); color: var(--text); }
  .field { display: grid; gap: 4px; font-size: 11px; color: var(--muted); flex: 1 1 200px; }
  .field.small { flex: 0 0 90px; }
  .examples { margin: 10px 0 4px; font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .chip { background: var(--surface-2); border: 1px solid var(--line); color: var(--text-2); border-radius: 999px; padding: 3px 10px; font-size: 12px; font-family: var(--mono); }
  .meta { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 12px; color: var(--muted); margin: 16px 0 8px; }
  .timing { color: var(--text-2); font-variant-numeric: tabular-nums; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; transition: opacity .2s; }
  .table-wrap.stale { opacity: .45; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 860px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 9px 10px; border-bottom: 1px solid var(--line); background: var(--surface-2); white-space: nowrap; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--grid); color: var(--text-2); vertical-align: top; }
  tr:last-child td { border-bottom: 0; }
  td small { display: block; color: var(--muted); }
  .mono { font-family: var(--mono); font-size: 11.5px; white-space: nowrap; color: var(--text); }
  .msg { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sev { display: inline-flex; width: 22px; height: 22px; align-items: center; justify-content: center; border-radius: 5px; font-weight: 600; color: #fff; background: var(--c); }
  /* Steps 3-5 of the ramp are light: white text would fall below 4.5:1. */
  .sev.light { color: #0b1115; }
  .pager { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
  .muted { color: var(--muted); font-size: 12px; }
  .state { color: var(--muted); font-size: 13px; padding: 18px 0; }
  .state.error { color: var(--critical-text); }
</style>
