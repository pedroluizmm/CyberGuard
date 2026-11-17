<script lang="ts">
  import { tick } from 'svelte'
  import Icon, { type IconName } from './Icon.svelte'
  import {
    ApiError, canonicalJson, CATEGORY_LABEL, getEvent, getPage, queryPath, SEVERITY_LABEL, SOURCE_ICON, SOURCE_LABEL,
    type Envelope, type EventPage, type QueryKind, type Source,
  } from './api'
  import { fmtMs, fmtUtc } from './format'

  let { source, from, to }: { source: Source; from: string; to: string } = $props()

  const kinds: { id: QueryKind; label: string; icon: IconName; field: string; placeholder: string; examples: string[] }[] = [
    { id: 'device', label: 'Q1 · Dispositivo', icon: 'server', field: 'device_id', placeholder: 'ex.: ids-sensor-06', examples: ['ids-sensor-06', 'vpn-gw-01', 'fw-edge-03'] },
    { id: 'ip', label: 'Q2 · IP de origem', icon: 'target', field: 'source_ip', placeholder: 'ex.: 2001:db8:bad:4::6', examples: ['2001:db8:bad:4::6', '203.0.113.173', '2001:db8:bad:3::16'] },
    { id: 'alerts', label: 'Q3 · Alertas', icon: 'alert', field: 'severity', placeholder: '1 a 5', examples: ['5', '4', '3'] },
  ]
  let kind = $state<QueryKind>('device')
  let value = $state('ids-sensor-06')
  let pageSize = $state(25)
  let cursors = $state<(string | null)[]>([null])
  let current = $state(0)
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
    selected = null
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
      selected = null
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('contract', 'unknown', 'Falha inesperada.')
      error = {
        kind: err.kind,
        message: err.kind === 'invalid' ? `Parâmetros rejeitados pela API: ${err.message}`
          : err.kind === 'network' ? 'A API local não está acessível. Inicie-a com python scripts/run_api.py start.'
          : err.kind === 'unavailable' || err.kind === 'timeout' ? `${SOURCE_LABEL[querySource]} indisponível no momento (${err.code}). Nenhum dado é exibido no lugar da consulta.`
          : err.message,
      }
      status = 'error'
    }
  }

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

  // ---- detail panel + READ by id (E1) on the source that produced the page ----
  let selected = $state<Envelope | null>(null)
  let detailHeading: HTMLHeadingElement | undefined = $state()
  let detailEl: HTMLElement | undefined = $state()
  type ReadCheck = { status: 'loading' } | { status: 'done'; http: number; db: number | null; source: Source; equal: boolean } | { status: 'error'; message: string }
  let readCheck = $state<ReadCheck | null>(null)
  let copied = $state(false)

  async function select(item: Envelope) {
    selected = item
    readCheck = null
    copied = false
    await tick()
    detailHeading?.focus({ preventScroll: true })
    if (window.innerWidth < 1280) detailEl?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  async function readById() {
    if (!selected || !timing) return
    const item = selected
    const src = timing.source
    readCheck = { status: 'loading' }
    try {
      const r = await getEvent(src, item.data.event_id)
      if (selected !== item) return
      readCheck = { status: 'done', http: r.httpMs, db: r.dbMs, source: src, equal: canonicalJson(r.raw) === canonicalJson(JSON.stringify(item)) }
    } catch (e) {
      if (selected !== item) return
      readCheck = { status: 'error', message: e instanceof ApiError ? `${e.message} (${e.code})` : 'Falha inesperada.' }
    }
  }
  async function copyId() {
    if (!selected) return
    try {
      await navigator.clipboard.writeText(selected.data.event_id)
      copied = true
    } catch {
      copied = false
    }
  }
</script>

<section class="card">
  <div class="card-head">
    <div><h2>Consulta de investigação</h2><p>Cada página é uma consulta real em {SOURCE_LABEL[source]} · janela de até 7 dias · ordem decrescente de tempo</p></div>
  </div>
  <form onsubmit={submit} class="form">
    <div class="segmented" role="radiogroup" aria-label="Padrão de consulta">
      {#each kinds as k (k.id)}
        <button type="button" role="radio" aria-checked={kind === k.id} class:on={kind === k.id} onclick={() => choose(k.id)}><Icon name={k.icon} size={15} />{k.label}</button>
      {/each}
    </div>
    <label class="field grow"><span class="mono">{spec.field}</span>
      <input bind:value placeholder={spec.placeholder} autocomplete="off" spellcheck="false" aria-invalid={!valid} />
    </label>
    <label class="field size"><span>Página</span>
      <select bind:value={pageSize}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select>
    </label>
    <button class="btn primary" type="submit" disabled={!valid || status === 'loading'}>
      {#if status === 'loading'}<span class="spinner"></span>Consultando…{:else}<Icon name="search" size={15} />Consultar{/if}
    </button>
  </form>
  <div class="examples"><span>Maiores partições da massa (manifesto):</span>
    {#each spec.examples as ex (ex)}<button type="button" class="chip mono" onclick={() => { value = ex; cursors = [null]; void load(0) }}>{ex}</button>{/each}
  </div>
</section>

<div class="results" class:with-detail={!!selected}>
  <section class="card list" aria-label="Resultados">
    {#if status === 'idle'}
      <div class="state">
        <h2><span class="icon-wrap"><Icon name="search" size={17} /></span>Nenhuma consulta executada</h2>
        <p>Escolha o padrão (Q1, Q2 ou Q3), informe o valor e clique em Consultar, ou use um dos exemplos. Os resultados vêm de {SOURCE_LABEL[source]}.</p>
      </div>
    {:else if status === 'error' && error}
      <div class="state error" role="alert">
        <h2><span class="icon-wrap"><Icon name="alert" size={17} /></span>Consulta não concluída</h2>
        <p>{error.message}</p>
        <button class="btn" onclick={() => load(current)}><Icon name="refresh" size={15} />Tentar novamente</button>
      </div>
    {:else if status === 'loading' && !page}
      <p class="sr-only" role="status">Consultando…</p>
      <div class="skeleton" style="height:22px;width:40%"></div>
      <div class="skeleton" style="height:260px;margin-top:14px"></div>
    {:else if page}
      <div class="meta" aria-live="polite">
        <span><strong>{page.items.length}</strong> {page.items.length === 1 ? 'evento' : 'eventos'} · página {current + 1}</span>
        {#if timing}
          <span class="timing">
            <span class="badge"><Icon name={SOURCE_ICON[timing.source]} size={13} />{SOURCE_LABEL[timing.source]}</span>
            <span class="badge">HTTP {fmtMs(timing.http)}</span>
            <span class="badge steel">banco {fmtMs(timing.db)}</span>
          </span>
        {/if}
      </div>
      {#if page.items.length === 0}
        <div class="state">
          <h2><span class="icon-wrap"><Icon name="info" size={17} /></span>Nenhum evento encontrado</h2>
          <p>Nenhum evento para <code>{spec.field} = {value}</code> no período selecionado.</p>
        </div>
      {:else}
        <div class="table-wrap" class:stale={status === 'loading'}>
          <table class="table events">
            <thead><tr><th>Ocorrência (UTC)</th><th>Dispositivo</th><th>IP de origem</th><th>Categoria · tipo</th><th>Sev.</th><th>Resultado</th><th>Mensagem</th></tr></thead>
            <tbody>
              {#each page.items as item (item.data.event_id)}
                <tr class:selected={selected?.data.event_id === item.data.event_id}>
                  <td><button class="row-btn mono" onclick={() => select(item)} aria-label={`Ver detalhes do evento de ${fmtUtc(item.data.occurred_at, true)} UTC`}>{fmtUtc(item.data.occurred_at, true)}</button></td>
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
        <button class="btn small" disabled={current === 0 || status === 'loading'} onclick={() => load(current - 1)}><Icon name="left" size={14} />Anterior</button>
        <span class="page-no">Página {current + 1}</span>
        <button class="btn small" disabled={!page.next_cursor || status === 'loading'} onclick={() => load(current + 1)}>Próxima<Icon name="right" size={14} /></button>
        <span class="muted">Paginação por cursor (keyset), sem OFFSET.</span>
      </div>
    {/if}
  </section>

  {#if selected}
    {@const d = selected.data}
    <aside class="card detail" aria-labelledby="detail-title" bind:this={detailEl}>
      <header>
        <h3 id="detail-title" tabindex="-1" bind:this={detailHeading}>Detalhes do evento</h3>
        <button class="btn ghost icon" onclick={() => (selected = null)} aria-label="Fechar detalhes"><Icon name="x" size={16} /></button>
      </header>
      <div class="headline">
        <span class="sev big" class:light={d.severity >= 3} style:--c={`var(--sev-${d.severity})`}>{d.severity}</span>
        <div><strong>{CATEGORY_LABEL[d.category]} · <span class="mono">{d.event_type}</span></strong><span>Severidade {d.severity} · {SEVERITY_LABEL[d.severity - 1]}</span></div>
      </div>
      <p class="message">{d.message}</p>
      <dl>
        <div class="full"><dt>ID do evento (UUID v4)</dt><dd class="mono id">{d.event_id}
          <button class="btn ghost icon" onclick={copyId} aria-label="Copiar ID" title={copied ? 'Copiado' : 'Copiar ID'}><Icon name={copied ? 'check' : 'copy'} size={14} /></button></dd></div>
        <div class="full"><dt>Ocorrência (UTC)</dt><dd class="mono">{d.occurred_at}</dd></div>
        <div><dt>Data (partição)</dt><dd class="mono">{d.event_date}</dd></div>
        <div><dt>Revisão</dt><dd>{selected.revision}</dd></div>
        <div><dt>Dispositivo</dt><dd class="mono">{d.device_id}</dd></div>
        <div><dt>IP de origem</dt><dd class="mono">{d.source_ip}</dd></div>
        <div><dt>Resultado</dt><dd>{d.outcome}</dd></div>
        <div><dt>Fonte</dt><dd>{timing ? SOURCE_LABEL[timing.source] : '—'}</dd></div>
      </dl>
      <p class="label">Metadados</p>
      <pre class="mono">{JSON.stringify(d.metadata, null, 2)}</pre>
      <div class="read">
        <button class="btn small" onclick={readById} disabled={readCheck?.status === 'loading'}>
          {#if readCheck?.status === 'loading'}<span class="spinner"></span>{:else}<Icon name="zap" size={14} />{/if}
          READ por ID{timing ? ` em ${SOURCE_LABEL[timing.source]}` : ''}
        </button>
        {#if readCheck?.status === 'done'}
          <p role="status"><span class="badge {readCheck.equal ? 'ok' : 'bad'}"><Icon name={readCheck.equal ? 'check' : 'x'} size={13} />{readCheck.equal ? 'idêntico ao item da página' : 'difere do item da página'}</span>
            <span class="muted">HTTP {fmtMs(readCheck.http)} · banco {fmtMs(readCheck.db)}</span></p>
        {:else if readCheck?.status === 'error'}
          <p class="err" role="alert">{readCheck.message}</p>
        {:else}
          <p class="muted">Consulta o registro canônico pelo UUID (operação do E1).</p>
        {/if}
      </div>
    </aside>
  {/if}
</div>

<style>
  .form { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .field.grow { flex: 1 1 220px; }
  .field.size { flex: 0 0 96px; }
  .field span.mono { font-size: 11.5px; }
  .examples { margin-top: 14px; font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .examples span { margin-right: 4px; }
  .examples .chip { font-size: 12px; min-height: 28px; padding: 3px 11px; }

  .results { display: grid; gap: 18px; align-items: start; }
  @media (min-width: 1280px) { .results.with-detail { grid-template-columns: minmax(0, 1fr) 380px; } }
  .list { min-height: 160px; }
  .meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--text-2); margin-bottom: 12px; }
  .meta strong { color: var(--text); }
  .timing { display: inline-flex; flex-wrap: wrap; gap: 6px; font-variant-numeric: tabular-nums; }
  .table-wrap { transition: opacity 0.2s; }
  .table-wrap.stale { opacity: 0.45; }
  .events { min-width: 900px; }
  .events td small { display: block; color: var(--muted); font-size: 11.5px; }
  .events td.mono { font-size: 12px; white-space: nowrap; color: var(--text); }
  .events .msg { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .events tr.selected { background: var(--accent-soft); }
  .events tr.selected td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
  .row-btn { background: none; border: 0; padding: 4px 6px; margin: -4px -6px; border-radius: 6px; color: var(--accent-text); font-size: 12px; white-space: nowrap; text-align: left;
    text-decoration: underline; text-decoration-color: rgba(60, 195, 211, 0.35); text-underline-offset: 3px; }
  .row-btn:hover { background: var(--accent-soft); text-decoration-color: currentColor; }
  .pager { display: flex; gap: 10px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
  .page-no { font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .pager .muted { font-size: 12px; margin-left: auto; }

  .detail { display: grid; gap: 14px; position: sticky; top: 16px; }
  .detail header { display: flex; justify-content: space-between; align-items: center; }
  .detail h3 { font-size: 14.5px; font-weight: 600; outline: none; }
  .headline { display: flex; gap: 12px; align-items: center; }
  .headline > div { display: grid; gap: 2px; font-size: 12.5px; color: var(--text-2); }
  .headline strong { color: var(--text); font-size: 14px; font-weight: 600; }
  .sev.big { width: 38px; height: 38px; border-radius: 11px; font-size: 16px; }
  .message { font-size: 13px; color: var(--text); line-height: 1.55; padding: 12px 14px; background: var(--card-2); border-radius: 10px; border: 1px solid var(--line-soft); }
  dl { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
  dl .full { grid-column: 1 / -1; }
  dt { font-size: 11.5px; color: var(--muted); margin-bottom: 3px; }
  dd { font-size: 13px; color: var(--text); overflow-wrap: anywhere; }
  dd.mono { font-size: 12px; }
  dd.id { display: flex; align-items: center; gap: 6px; }
  dd.id .btn { width: 26px; min-height: 26px; border-color: transparent; }
  .label { font-size: 11.5px; color: var(--muted); margin-bottom: -6px; }
  pre { margin: 0; font-size: 11.5px; line-height: 1.5; color: var(--text-2); background: var(--bg); border: 1px solid var(--line-soft); border-radius: 10px;
    padding: 10px 12px; max-height: 180px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
  .read { display: grid; gap: 8px; padding-top: 12px; border-top: 1px solid var(--line-soft); }
  .read .btn { justify-self: start; }
  .read p { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; }
  .read .err { color: var(--critical-text); }
  @media (max-width: 1279px) { .detail { position: static; } }
  @media (max-width: 640px) {
    .segmented { width: 100%; }
    .segmented button { flex: 1 1 auto; justify-content: center; }
    .form .btn.primary { flex: 1 1 100%; }
    .pager .muted { margin-left: 0; flex-basis: 100%; }
    dl { grid-template-columns: 1fr; }
  }
</style>
