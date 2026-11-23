<script lang="ts">
  import Icon from './Icon.svelte'
  import ScaleChart from './ScaleChart.svelte'
  import { SOURCE_LABEL, SOURCE_SHORT, SOURCES, type Campaign, type ScaleOperation, type ScalePoint, type Source } from './api'
  import { fmtBytes, fmtDelta, fmtEvents, fmtInt, fmtMs, fmtRatio } from './format'

  // Same code, parameters and protocol at every dataset size of the campaign; values come from
  // benchmarks/results/summary.json (campaigns.escala), never from the browser.
  let { campaign }: { campaign: Campaign } = $props()

  const sizes = $derived(campaign.scale.sizes)
  const lo = $derived(sizes[0])
  const hi = $derived(sizes[sizes.length - 1])
  const ops = $derived(campaign.scale.operations)
  const at = (op: ScaleOperation | undefined, n: number) => op?.points.find((p) => p.logical_events === n)
  const med = (p: ScalePoint | undefined, s: Source) => p?.[s].http.median ?? null
  const byId = (id: string) => ops.find((o) => o.id === id)
  const panel = $derived(byId('overview_7d'))
  const keyed = $derived(ops.filter((o) => o.class === 'chave' || o.class === 'pagina_fixa'))
  const allEquivalent = $derived(ops.every((o) => o.points.every((p) => p.equivalent)))
  const entry = (n: number) => campaign.sizes.find((s) => s.logical_events === n)
  const env = (n: number) => (entry(n)?.main.environment ?? {}) as Record<string, any>
  type Power = { on_ac_power?: boolean; battery_percent?: number }
  // Power is recorded per run; when the main run predates that field, use the E6 run of the same size.
  const power = (n: number): Power | undefined => (env(n).host?.power
    ?? (entry(n)?.durability?.environment?.host as Record<string, any> | undefined)?.power) as Power | undefined
  const powerText = (n: number) => { const p = power(n); return !p ? 'não registrada' : p.on_ac_power ? 'tomada' : `bateria (${p.battery_percent}%)` }
  const mixedPower = $derived(new Set(sizes.map((n) => power(n)?.on_ac_power).filter((v) => v !== undefined)).size > 1)
  const writesAt = (n: number, config: 'padrao' | 'antes_do_fsync') => campaign.scale.writes.find((w) => w.logical_events === n && w.config === config)
  const controlAt = (n: number) => campaign.scale.control.find((c) => c.logical_events === n)
  const pgBytes = (n: number) => Number(env(n).postgresql?.database_bytes ?? NaN)
  const csBytes = (n: number) => Number(env(n).cassandra?.du_bytes?.['/var/lib/cassandra/data/cyberguard'] ?? NaN)
  const range = (values: number[]) => values.length ? `${fmtDelta(1, 1 + Math.min(...values) / 100)} a ${fmtDelta(1, 1 + Math.max(...values) / 100)}` : '—'
  const pct = (a: number | null, b: number | null) => (a && b !== null ? (100 * (b - a)) / a : null)
  const deltas = (s: Source) => keyed.map((o) => pct(med(at(o, lo), s), med(at(o, hi), s))).filter((v): v is number => v !== null)

  const CLASS_LABEL: Record<string, string> = {
    chave: 'Chave · 1 evento', pagina_fixa: 'Página fixa', resposta_crescente: 'Resposta cresce', agregacao: 'Agregação',
  }
  /** Largest deviation between a replicate and the main run at the largest size (between-run noise). */
  const noise = $derived(Math.max(0.1, ...ops.flatMap((o) => {
    const b = at(o, hi)
    return (b?.replicates ?? []).flatMap((r) => SOURCES.map((s) => {
      const main = med(b, s), rep = r[s]
      return main && rep ? Math.abs(rep / main - 1) : 0
    }))
  })))
  /** How the gap between the databases moved from the smallest to the largest size, against the measured noise. */
  function trend(op: ScaleOperation): string {
    const a = at(op, lo), b = at(op, hi)
    if (!a?.faster || !b?.faster || !a.ratio || !b.ratio) return '—'
    if (a.faster !== b.faster) return `inverteu (${SOURCE_SHORT[b.faster]} vence)`
    const change = (b.ratio - a.ratio) / a.ratio
    if (Math.abs(change) <= noise) return 'dentro do ruído'
    return change > 0 ? `aumentou (${SOURCE_SHORT[b.faster]})` : `diminuiu (${SOURCE_SHORT[b.faster]})`
  }
</script>

<section class="card intro">
  <div class="card-head">
    <div>
      <h2>Comparação entre volumes · {sizes.map(fmtEvents).join(' → ')} eventos</h2>
      <p>Mesma máquina, mesmo código, mesmos parâmetros e o mesmo protocolo em cada volume (pré-aquecimento descartado, 5 aquecimentos, 30 medições por banco)</p>
    </div>
    <div class="aside">
      <span class="badge {allEquivalent ? 'ok' : 'bad'}"><Icon name={allEquivalent ? 'check' : 'x'} size={13} />{allEquivalent ? 'Resposta idêntica nos dois bancos em todas as medições' : 'Há operações com resposta divergente'}</span>
    </div>
  </div>
  <dl class="facts">
    {#each sizes as n (n)}
      <div>
        <dt>{fmtEvents(n)}</dt>
        <dd>{fmtInt(n)} eventos em cada banco</dd>
        <dd class="sub">PG {fmtBytes(pgBytes(n))} · Cassandra {fmtBytes(csBytes(n))} (keyspace) · energia: {powerText(n)}</dd>
      </div>
    {/each}
  </dl>
  {#if mixedPower}
    <p class="warn"><Icon name="alert" size={14} />As execuções não tiveram a mesma fonte de energia do notebook; compare as razões PG × Cassandra (medidas em pares) antes das variações absolutas.</p>
  {/if}
</section>

<section class="highlights" aria-label="O que mudou com o volume">
  {#if panel}
    {@const a = at(panel, lo)}
    {@const b = at(panel, hi)}
    <article class="card hl nosql">
      <p class="kicker"><Icon name="layers" size={15} />Painel agregado 7 dias · E4</p>
      <p class="value">{fmtRatio(a?.ratio)} → {fmtRatio(b?.ratio)}<small>{b?.faster ? SOURCE_LABEL[b.faster] : ''}</small></p>
      <p class="text">PostgreSQL {fmtMs(med(a, 'postgresql'))} → {fmtMs(med(b, 'postgresql'))} ({fmtDelta(med(a, 'postgresql'), med(b, 'postgresql'))}) ao agregar {fmtInt(a?.covered_events ?? 0)} → {fmtInt(b?.covered_events ?? 0)} eventos. Cassandra {fmtMs(med(a, 'cassandra'))} → {fmtMs(med(b, 'cassandra'))} ({fmtDelta(med(a, 'cassandra'), med(b, 'cassandra'))}).</p>
      <p class="caveat">O rollup lê as mesmas ≤ 2 520 células em qualquer volume; o PostgreSQL visita uma entrada de índice por evento do período.</p>
    </article>
  {/if}
  {#if keyed.length}
    <article class="card hl">
      <p class="kicker"><Icon name="search" size={15} />Buscas por chave e páginas · E1–E3</p>
      <p class="value small">PG {range(deltas('postgresql'))}<br />CS {range(deltas('cassandra'))}</p>
      <p class="text">Variação da mediana de {fmtEvents(lo)} para {fmtEvents(hi)} nas {keyed.length} leituras com resposta de tamanho fixo, dentro do ruído entre execuções (até {Math.round(noise * 100)}%). Vencedor em {fmtEvents(hi)}: {[...new Set(keyed.map((o) => at(o, hi)?.faster).filter(Boolean))].map((s) => SOURCE_LABEL[s as Source]).join(' e ')}.</p>
      <p class="caveat">B-tree (PG) e partição + clustering (Cassandra) mantêm o custo quase independente do total; muda o volume que precisa caber em cache.</p>
    </article>
  {/if}
  {#if writesAt(lo, 'padrao') && writesAt(hi, 'padrao')}
    {@const a = writesAt(lo, 'padrao')!}
    {@const b = writesAt(hi, 'padrao')!}
    <article class="card hl">
      <p class="kicker"><Icon name="zap" size={15} />CREATE concorrente · E6</p>
      <p class="value small">PG {fmtMs(a.create.postgresql.median_ms)} → {fmtMs(b.create.postgresql.median_ms)}<br />CS {fmtMs(a.create.cassandra.median_ms)} → {fmtMs(b.create.cassandra.median_ms)}</p>
      <p class="text">Durabilidade padrão (PG fsync por commit × commitlog periódico). {Math.max(...SOURCES.map((s) => Math.abs((b.create[s].median_ms ?? 0) / (a.create[s].median_ms || 1) - 1))) <= noise ? 'Sem efeito mensurável do volume: as variações ficaram dentro do ruído entre execuções.' : 'A variação passou do ruído entre execuções; veja a tabela E6.'}</p>
      <p class="caveat">A comparação com a mesma política de confirmação está na tabela E6 abaixo.</p>
    </article>
  {/if}
  <article class="card hl">
    <p class="kicker"><Icon name="server" size={15} />Armazenamento</p>
    <p class="value small">PG {fmtBytes(pgBytes(lo))} → {fmtBytes(pgBytes(hi))}<br />CS {fmtBytes(csBytes(lo))} → {fmtBytes(csBytes(hi))}</p>
    <p class="text">Banco PostgreSQL inteiro (tabelas + índices) e keyspace Cassandra (canônico + 3 projeções + rollup, LZ4) medidos antes de cada benchmark.</p>
    <p class="caveat">Tamanhos dependem de compressão, compactação e fillfactor; não são comparação de eficiência.</p>
  </article>
</section>

<section class="card">
  <div class="card-head">
    <div><h2>Mediana HTTP por volume, em ms</h2><p>Faixa clara = p25–p75 · círculo = PostgreSQL, losango = Cassandra · rodapé: variação de {fmtEvents(lo)} para {fmtEvents(hi)} e vencedor no maior volume</p></div>
  </div>
  <div class="tiles">
    {#each ops as op (op.id)}<ScaleChart {op} />{/each}
  </div>
</section>

<section class="card">
  <div class="card-head"><div><h2>Tabela consolidada</h2><p>Medianas HTTP (ms) · eventos cobertos = linhas do período/filtro no PostgreSQL, contadas antes de cada execução</p></div></div>
  <div class="table-wrap">
    <table class="table wide">
      <thead><tr><th>Operação</th><th>Classe</th><th class="num">Eventos cobertos</th><th class="num">PG {fmtEvents(lo)}</th><th class="num">CS {fmtEvents(lo)}</th><th class="num">PG {fmtEvents(hi)}</th><th class="num">CS {fmtEvents(hi)}</th><th class="num">Δ PG</th><th class="num">Δ CS</th><th>Razão {fmtEvents(lo)} → {fmtEvents(hi)}</th><th>Diferença</th></tr></thead>
      <tbody>
        {#each ops as op (op.id)}
          {@const a = at(op, lo)}
          {@const b = at(op, hi)}
          <tr class:nosql={b?.faster === 'cassandra'}>
            <td><span class="exp">{op.experiment}</span> {op.title}</td>
            <td class="muted">{CLASS_LABEL[op.class ?? ''] ?? '—'}</td>
            <td class="num muted">{a?.covered_events != null ? `${fmtInt(a.covered_events)} → ${fmtInt(b?.covered_events ?? 0)}` : 'chave'}</td>
            <td class="num">{fmtMs(med(a, 'postgresql'))}{@render rep(a, 'postgresql')}</td><td class="num">{fmtMs(med(a, 'cassandra'))}{@render rep(a, 'cassandra')}</td>
            <td class="num">{fmtMs(med(b, 'postgresql'))}{@render rep(b, 'postgresql')}</td><td class="num">{fmtMs(med(b, 'cassandra'))}{@render rep(b, 'cassandra')}</td>
            <td class="num"><strong>{fmtDelta(med(a, 'postgresql'), med(b, 'postgresql'))}</strong></td>
            <td class="num"><strong>{fmtDelta(med(a, 'cassandra'), med(b, 'cassandra'))}</strong></td>
            <td>{a?.faster ? `${SOURCE_SHORT[a.faster]} ${fmtRatio(a.ratio)}` : '—'} → {b?.faster ? `${SOURCE_SHORT[b.faster]} ${fmtRatio(b.ratio)}` : '—'}</td>
            <td>{trend(op)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="note">Razão = mediana do mais lento ÷ mediana do mais rápido, no mesmo volume (pares intercalados). Em cinza, a mediana de outra execução no mesmo volume (réplica): ela variou até {Math.round(noise * 100)}%. “Diferença” compara a razão do menor e do maior volume e só aponta aumento ou queda acima desse ruído.</p>
</section>

{#snippet rep(p: ScalePoint | undefined, s: Source)}
  {#each p?.replicates ?? [] as r (r.run_id)}<small class="rep" title="Réplica {r.run_id}">{fmtMs(r[s])}</small>{/each}
{/snippet}

<div class="two">
  <section class="card">
    <div class="card-head"><div><h2>Controle E5 · pré-agregação no PostgreSQL</h2><p>Painel 7 dias · psql \timing (PG) e Server-Timing (Cassandra) · medianas</p></div></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Volume</th><th class="num">PG agregação</th><th class="num">PG view materializada</th><th class="num">PG REFRESH completo</th><th class="num">Cassandra rollup</th></tr></thead>
        <tbody>
          {#each sizes as n (n)}
            {@const c = controlAt(n)}
            <tr><td>{fmtEvents(n)}</td><td class="num">{fmtMs(c?.pg_on_read_aggregate_7d)}</td><td class="num"><strong>{fmtMs(c?.pg_mv_read_7d)}</strong></td><td class="num">{fmtMs(c?.pg_mv_refresh_full)}</td><td class="num"><strong>{fmtMs(c?.cassandra_rollup_db_7d)}</strong></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note">A leitura pré-agregada fica constante nos dois bancos. O custo se desloca: no PostgreSQL, o REFRESH recalcula a tabela inteira e cresce com o volume; no Cassandra, cada CREATE incrementa um contador (custo no E6) e desvios são corrigidos por reconciliação.</p>
  </section>
  <section class="card">
    <div class="card-head"><div><h2>E6 · mediana de latência por operação</h2><p>8 clientes · 10 rodadas × 100 eventos · PG / Cassandra</p></div></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Volume</th><th>Política</th><th class="num">CREATE</th><th class="num">UPDATE</th><th class="num">DELETE</th></tr></thead>
        <tbody>
          {#each sizes as n (n)}
            {#each (['padrao', 'antes_do_fsync'] as const) as config (config)}
              {@const w = writesAt(n, config)}
              {#if w}
                <tr><td>{fmtEvents(n)}</td><td class="muted">{config === 'padrao' ? 'padrão' : 'antes do fsync'}</td>
                  {#each (['create', 'update', 'delete'] as const) as op (op)}
                    {@const pg = w[op].postgresql.median_ms ?? Infinity}
                    {@const cs = w[op].cassandra.median_ms ?? Infinity}
                    <td class="num">{#if pg <= cs}<strong>{fmtMs(w[op].postgresql.median_ms)}</strong>{:else}{fmtMs(w[op].postgresql.median_ms)}{/if} / {#if cs < pg}<strong>{fmtMs(w[op].cassandra.median_ms)}</strong>{:else}{fmtMs(w[op].cassandra.median_ms)}{/if}</td>
                  {/each}
                </tr>
              {/if}
            {/each}
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note">Padrão: PostgreSQL synchronous_commit=on (fsync do WAL por commit) × Cassandra commitlog periódico (10 s). “Antes do fsync”: PostgreSQL synchronous_commit=off; as janelas de perda continuam diferentes (~0,6 s × até 10 s). Em negrito, o menor valor.</p>
  </section>
</div>

<section class="card limits">
  <div class="card-head"><div><h2>Como ler esta comparação</h2><p>O que muda com o volume e o que não pode ser concluído</p></div></div>
  <ul>
    <li><strong>Agregação:</strong> o PostgreSQL normalizado agrega na leitura e seu custo acompanha o número de eventos do período; o rollup Cassandra é pré-agregado na escrita e lê sempre o mesmo número de células. A vantagem mede a pré-agregação, não um motor mais rápido (ver E5).</li>
    <li><strong>Chave e páginas fixas:</strong> índice B-tree e partição/clustering mantêm a profundidade de busca quase constante; mudanças vêm de cache e de partições maiores, não de varrer mais dados.</li>
    <li><strong>Um nó Cassandra (RF=1):</strong> crescer a massa em uma máquina não demonstra escalabilidade horizontal, replicação nem tolerância a falhas.</li>
    <li><strong>Recursos assimétricos:</strong> limites de 5 GiB (Cassandra) e 2 GiB (PostgreSQL), sem limite de CPU, mantidos iguais em todos os volumes para isolar o efeito da massa.</li>
  </ul>
</section>

<style>
  .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1px; background: var(--line-soft); border: 1px solid var(--line-soft); border-radius: 12px; overflow: hidden; }
  .facts > div { background: var(--card); padding: 12px 14px; display: grid; gap: 3px; align-content: start; }
  .facts dt { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
  .facts dd { font-size: 12.5px; color: var(--text); }
  .facts dd.sub { font-size: 11.5px; color: var(--text-2); line-height: 1.45; }
  .warn { display: flex; gap: 8px; align-items: flex-start; margin-top: 12px; font-size: 12px; color: var(--warning); line-height: 1.5; }
  .intro .badge { white-space: normal; }

  .highlights { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
  .hl { display: flex; flex-direction: column; gap: 8px; }
  .hl.nosql { background: var(--hero); border-color: var(--hero-line); }
  .kicker { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-2); font-weight: 550; }
  .hl.nosql .kicker { color: #c3cde0; }
  .value { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; margin-top: 4px; }
  .value.small { font-size: 17px; letter-spacing: -0.01em; line-height: 1.35; }
  .value small { font-size: 13px; font-weight: 550; color: var(--text-2); margin-left: 8px; letter-spacing: 0; }
  .hl.nosql .value small { color: #c3cde0; }
  .text { font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
  .hl.nosql .text { color: #d5ddeb; }
  .caveat { margin-top: auto; padding-top: 10px; border-top: 1px solid var(--line-soft); font-size: 11.5px; color: var(--muted); line-height: 1.5; }
  .hl.nosql .caveat { border-color: var(--hero-line); color: #c3cde0; }

  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
  .two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
  .wide { min-width: 1040px; }
  .table { min-width: 460px; }
  .exp { font-family: var(--mono); font-size: 11px; color: var(--muted); margin-right: 4px; }
  .rep { display: block; font-size: 10.5px; color: var(--muted); }
  tr.nosql td:first-child { box-shadow: inset 3px 0 0 var(--steel); }
  .note { margin-top: 12px; }
  .limits ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
  .limits li { font-size: 13px; color: var(--text-2); line-height: 1.55; }
  .limits li::marker { color: var(--steel); }
  .limits strong { color: var(--text); font-weight: 600; }

  @media (max-width: 1360px) { .highlights { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 1100px) { .two { grid-template-columns: 1fr; } }
  @media (max-width: 560px) { .highlights { grid-template-columns: 1fr; } }
</style>
